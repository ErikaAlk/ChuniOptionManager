using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;

namespace ChuniOptionManager.Services;

public enum CharacterImageKind
{
    Big,
    Small,
    Thumb
}

public sealed class CropSettings
{
    public double Zoom { get; set; } = 1.0;
    public double OffsetX { get; set; }
    public double OffsetY { get; set; }
}

public static class DdsImageGenerator
{
    public static void GenerateCharacterDds(string sourceImagePath, string destinationFolder, IReadOnlyDictionary<CharacterImageKind, CropSettings> crops)
    {
        if (!File.Exists(sourceImagePath))
        {
            throw new FileNotFoundException("找不到源图片。", sourceImagePath);
        }

        Directory.CreateDirectory(destinationFolder);
        using var source = new Bitmap(sourceImagePath);
        WriteDxt5Dds(RenderSquare(source, 1080, crops.GetValueOrDefault(CharacterImageKind.Big) ?? new CropSettings()), Path.Combine(destinationFolder, "big.dds"));
        WriteDxt5Dds(RenderSquare(source, 512, crops.GetValueOrDefault(CharacterImageKind.Small) ?? new CropSettings()), Path.Combine(destinationFolder, "small.dds"));
        WriteDxt5Dds(RenderSquare(source, 128, crops.GetValueOrDefault(CharacterImageKind.Thumb) ?? new CropSettings()), Path.Combine(destinationFolder, "thumb.dds"));
    }

    private static Bitmap RenderSquare(Bitmap source, int outputSize, CropSettings crop)
    {
        var minSide = Math.Min(source.Width, source.Height);
        var zoom = Math.Clamp(crop.Zoom, 1.0, 10.0);
        var cropSize = minSide / zoom;
        var maxX = Math.Max(0, source.Width - cropSize);
        var maxY = Math.Max(0, source.Height - cropSize);
        var left = maxX * ((Math.Clamp(crop.OffsetX, -100, 100) + 100) / 200.0);
        var top = maxY * ((Math.Clamp(crop.OffsetY, -100, 100) + 100) / 200.0);

        var output = new Bitmap(outputSize, outputSize, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(output);
        graphics.Clear(Color.Transparent);
        graphics.CompositingQuality = CompositingQuality.HighQuality;
        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
        graphics.SmoothingMode = SmoothingMode.HighQuality;
        graphics.DrawImage(
            source,
            new Rectangle(0, 0, outputSize, outputSize),
            new RectangleF((float)left, (float)top, (float)cropSize, (float)cropSize),
            GraphicsUnit.Pixel);
        return output;
    }

    private static void WriteDxt5Dds(Bitmap baseBitmap, string path)
    {
        using (baseBitmap)
        using (var stream = File.Create(path))
        using (var writer = new BinaryWriter(stream))
        {
            var mipmaps = BuildMipmaps(baseBitmap);
            WriteDdsHeader(writer, baseBitmap.Width, baseBitmap.Height, mipmaps.Count);

            foreach (var mipmap in mipmaps)
            {
                using (mipmap)
                {
                    var pixels = ReadPixels(mipmap);
                    WriteDxt5Pixels(writer, pixels, mipmap.Width, mipmap.Height);
                }
            }
        }
    }

    private static List<Bitmap> BuildMipmaps(Bitmap baseBitmap)
    {
        var bitmaps = new List<Bitmap>();
        var current = new Bitmap(baseBitmap);
        bitmaps.Add(current);

        while (current.Width > 1 || current.Height > 1)
        {
            var width = Math.Max(1, current.Width / 2);
            var height = Math.Max(1, current.Height / 2);
            var next = new Bitmap(width, height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
            using var graphics = Graphics.FromImage(next);
            graphics.CompositingQuality = CompositingQuality.HighQuality;
            graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
            graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
            graphics.DrawImage(current, new Rectangle(0, 0, width, height));
            bitmaps.Add(next);
            current = next;
        }

        return bitmaps;
    }

    private static Rgba[] ReadPixels(Bitmap bitmap)
    {
        var rect = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
        var data = bitmap.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            var bytes = new byte[data.Stride * bitmap.Height];
            Marshal.Copy(data.Scan0, bytes, 0, bytes.Length);
            var pixels = new Rgba[bitmap.Width * bitmap.Height];
            for (var y = 0; y < bitmap.Height; y++)
            {
                var row = y * data.Stride;
                for (var x = 0; x < bitmap.Width; x++)
                {
                    var sourceIndex = row + x * 4;
                    pixels[y * bitmap.Width + x] = new Rgba(
                        bytes[sourceIndex + 2],
                        bytes[sourceIndex + 1],
                        bytes[sourceIndex],
                        bytes[sourceIndex + 3]);
                }
            }

            return pixels;
        }
        finally
        {
            bitmap.UnlockBits(data);
        }
    }

    private static void WriteDdsHeader(BinaryWriter writer, int width, int height, int mipMapCount)
    {
        writer.Write(0x20534444u);
        writer.Write(124u);
        writer.Write(0x000A1007u);
        writer.Write((uint)height);
        writer.Write((uint)width);
        writer.Write((uint)(Math.Max(1, (width + 3) / 4) * Math.Max(1, (height + 3) / 4) * 16));
        writer.Write(0u);
        writer.Write((uint)mipMapCount);
        for (var i = 0; i < 11; i++)
        {
            writer.Write(0u);
        }

        writer.Write(32u);
        writer.Write(0x00000004u);
        writer.Write(0x35545844u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0x00401008u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
    }

    private static void WriteDxt5Pixels(BinaryWriter writer, Rgba[] pixels, int width, int height)
    {
        var blocksX = Math.Max(1, (width + 3) / 4);
        var blocksY = Math.Max(1, (height + 3) / 4);
        var block = new Rgba[16];

        for (var by = 0; by < blocksY; by++)
        {
            for (var bx = 0; bx < blocksX; bx++)
            {
                for (var py = 0; py < 4; py++)
                {
                    var y = Math.Min(height - 1, by * 4 + py);
                    for (var px = 0; px < 4; px++)
                    {
                        var x = Math.Min(width - 1, bx * 4 + px);
                        block[py * 4 + px] = pixels[y * width + x];
                    }
                }

                WriteDxt5Block(writer, block);
            }
        }
    }

    private static void WriteDxt5Block(BinaryWriter writer, Rgba[] block)
    {
        WriteAlphaBlock(writer, block);
        WriteColorBlock(writer, block);
    }

    private static void WriteAlphaBlock(BinaryWriter writer, Rgba[] block)
    {
        var min = block.Min(pixel => pixel.A);
        var max = block.Max(pixel => pixel.A);
        var alpha0 = max;
        var alpha1 = min;
        writer.Write(alpha0);
        writer.Write(alpha1);

        var palette = new byte[8];
        palette[0] = alpha0;
        palette[1] = alpha1;
        if (alpha0 > alpha1)
        {
            palette[2] = (byte)((6 * alpha0 + alpha1) / 7);
            palette[3] = (byte)((5 * alpha0 + 2 * alpha1) / 7);
            palette[4] = (byte)((4 * alpha0 + 3 * alpha1) / 7);
            palette[5] = (byte)((3 * alpha0 + 4 * alpha1) / 7);
            palette[6] = (byte)((2 * alpha0 + 5 * alpha1) / 7);
            palette[7] = (byte)((alpha0 + 6 * alpha1) / 7);
        }
        else
        {
            palette[2] = (byte)((4 * alpha0 + alpha1) / 5);
            palette[3] = (byte)((3 * alpha0 + 2 * alpha1) / 5);
            palette[4] = (byte)((2 * alpha0 + 3 * alpha1) / 5);
            palette[5] = (byte)((alpha0 + 4 * alpha1) / 5);
            palette[6] = 0;
            palette[7] = 255;
        }

        ulong indices = 0;
        for (var i = 0; i < 16; i++)
        {
            var best = 0;
            var bestDistance = int.MaxValue;
            for (var j = 0; j < 8; j++)
            {
                var distance = Math.Abs(block[i].A - palette[j]);
                if (distance < bestDistance)
                {
                    best = j;
                    bestDistance = distance;
                }
            }

            indices |= ((ulong)best & 0x7) << (3 * i);
        }

        for (var i = 0; i < 6; i++)
        {
            writer.Write((byte)((indices >> (8 * i)) & 0xFF));
        }
    }

    private static void WriteColorBlock(BinaryWriter writer, Rgba[] block)
    {
        var bestA = block[0];
        var bestB = block[0];
        var bestDistance = -1;

        for (var i = 0; i < block.Length; i++)
        {
            for (var j = i + 1; j < block.Length; j++)
            {
                var distance = ColorDistance(block[i], block[j]);
                if (distance > bestDistance)
                {
                    bestDistance = distance;
                    bestA = block[i];
                    bestB = block[j];
                }
            }
        }

        var color0 = ToRgb565(bestA);
        var color1 = ToRgb565(bestB);
        if (color0 < color1)
        {
            (color0, color1) = (color1, color0);
        }

        var palette = new Rgba[4];
        palette[0] = FromRgb565(color0);
        palette[1] = FromRgb565(color1);
        palette[2] = new Rgba((byte)((2 * palette[0].R + palette[1].R) / 3), (byte)((2 * palette[0].G + palette[1].G) / 3), (byte)((2 * palette[0].B + palette[1].B) / 3), 255);
        palette[3] = new Rgba((byte)((palette[0].R + 2 * palette[1].R) / 3), (byte)((palette[0].G + 2 * palette[1].G) / 3), (byte)((palette[0].B + 2 * palette[1].B) / 3), 255);

        uint indices = 0;
        for (var i = 0; i < 16; i++)
        {
            var best = 0;
            var distance = int.MaxValue;
            for (var j = 0; j < 4; j++)
            {
                var candidate = ColorDistance(block[i], palette[j]);
                if (candidate < distance)
                {
                    distance = candidate;
                    best = j;
                }
            }

            indices |= ((uint)best & 0x3) << (2 * i);
        }

        writer.Write(color0);
        writer.Write(color1);
        writer.Write(indices);
    }

    private static ushort ToRgb565(Rgba color)
    {
        return (ushort)(((color.R >> 3) << 11) | ((color.G >> 2) << 5) | (color.B >> 3));
    }

    private static Rgba FromRgb565(ushort color)
    {
        var r = (byte)(((color >> 11) & 31) * 255 / 31);
        var g = (byte)(((color >> 5) & 63) * 255 / 63);
        var b = (byte)((color & 31) * 255 / 31);
        return new Rgba(r, g, b, 255);
    }

    private static int ColorDistance(Rgba a, Rgba b)
    {
        var dr = a.R - b.R;
        var dg = a.G - b.G;
        var db = a.B - b.B;
        return dr * dr + dg * dg + db * db;
    }

    private readonly record struct Rgba(byte R, byte G, byte B, byte A);
}
