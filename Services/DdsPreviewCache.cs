using System.Buffers.Binary;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace ChuniOptionManager.Services;

public static class DdsPreviewCache
{
    private static readonly string CacheRoot = Path.Combine(Path.GetTempPath(), "ChuniOptionManager", "dds-preview");

    public static string GetPreviewPath(string path)
    {
        if (!File.Exists(path) || !path.EndsWith(".dds", StringComparison.OrdinalIgnoreCase))
        {
            return path;
        }

        try
        {
            Directory.CreateDirectory(CacheRoot);
            var info = new FileInfo(path);
            var keySource = $"{path}|{info.Length}|{info.LastWriteTimeUtc.Ticks}";
            var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(keySource)));
            var previewPath = Path.Combine(CacheRoot, key + ".png");
            if (File.Exists(previewPath))
            {
                return previewPath;
            }

            // 先解码到唯一的临时文件，再原子地 Move 到最终路径。
            // 否则进程在 bitmap.Save 中途被杀/磁盘满/并发写，都会在缓存里留下一个截断的 PNG，
            // 而缓存键（路径|大小|mtime）不变，这个坏文件会被后续每次运行永久命中。
            var tempPath = previewPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            DecodeToPng(path, tempPath);
            try
            {
                File.Move(tempPath, previewPath);
            }
            catch (IOException)
            {
                // 另一个线程/进程已经抢先生成了同一个预览：保留它的，删掉我们的临时文件。
                TryDelete(tempPath);
            }

            return previewPath;
        }
        catch
        {
            return path;
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch
        {
            // 临时文件清理失败可忽略。
        }
    }

    private static void DecodeToPng(string sourcePath, string destinationPath)
    {
        var data = File.ReadAllBytes(sourcePath);
        if (data.Length < 128 || Encoding.ASCII.GetString(data, 0, 4) != "DDS ")
        {
            throw new InvalidDataException("Unsupported DDS file.");
        }

        var height = BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(12, 4));
        var width = BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(16, 4));
        var fourCc = Encoding.ASCII.GetString(data, 84, 4);
        var dataOffset = 128;
        if (fourCc == "DX10")
        {
            throw new InvalidDataException("DX10 DDS header is not supported.");
        }

        if (width <= 0 || height <= 0)
        {
            throw new InvalidDataException("Invalid DDS size.");
        }

        var pixels = fourCc switch
        {
            "DXT1" => DecodeDxt(data, dataOffset, width, height, 8, AlphaMode.None),
            "DXT3" => DecodeDxt(data, dataOffset, width, height, 16, AlphaMode.Explicit),
            "DXT5" => DecodeDxt(data, dataOffset, width, height, 16, AlphaMode.Interpolated),
            _ => throw new InvalidDataException($"Unsupported DDS format {fourCc}.")
        };

        using var bitmap = new Bitmap(width, height, PixelFormat.Format32bppArgb);
        var rect = new Rectangle(0, 0, width, height);
        var bitmapData = bitmap.LockBits(rect, ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
        try
        {
            Marshal.Copy(pixels, 0, bitmapData.Scan0, pixels.Length);
        }
        finally
        {
            bitmap.UnlockBits(bitmapData);
        }

        bitmap.Save(destinationPath, ImageFormat.Png);
    }

    private static byte[] DecodeDxt(byte[] data, int offset, int width, int height, int blockSize, AlphaMode alphaMode)
    {
        var pixels = new byte[width * height * 4];
        var blockCountX = (width + 3) / 4;
        var blockCountY = (height + 3) / 4;

        for (var blockY = 0; blockY < blockCountY; blockY++)
        {
            for (var blockX = 0; blockX < blockCountX; blockX++)
            {
                var blockOffset = offset + (blockY * blockCountX + blockX) * blockSize;
                if (blockOffset + blockSize > data.Length)
                {
                    continue;
                }

                var alphaValues = ReadAlphaValues(data, blockOffset, alphaMode);
                var colorOffset = alphaMode == AlphaMode.None ? blockOffset : blockOffset + 8;
                var color0 = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(colorOffset, 2));
                var color1 = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(colorOffset + 2, 2));
                var colors = BuildColorTable(color0, color1, alphaMode != AlphaMode.None);
                var colorBits = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(colorOffset + 4, 4));

                for (var y = 0; y < 4; y++)
                {
                    for (var x = 0; x < 4; x++)
                    {
                        var targetX = blockX * 4 + x;
                        var targetY = blockY * 4 + y;
                        if (targetX >= width || targetY >= height)
                        {
                            continue;
                        }

                        var index = y * 4 + x;
                        var colorIndex = (int)((colorBits >> (2 * index)) & 0x03);
                        var color = colors[colorIndex];
                        var alpha = alphaValues?[index] ?? color.Alpha;
                        var target = (targetY * width + targetX) * 4;
                        pixels[target] = color.Blue;
                        pixels[target + 1] = color.Green;
                        pixels[target + 2] = color.Red;
                        pixels[target + 3] = alpha;
                    }
                }
            }
        }

        return pixels;
    }

    private static byte[]? ReadAlphaValues(byte[] data, int blockOffset, AlphaMode mode)
    {
        if (mode == AlphaMode.None)
        {
            return null;
        }

        var alphaValues = new byte[16];
        if (mode == AlphaMode.Explicit)
        {
            var alphaBits = BinaryPrimitives.ReadUInt64LittleEndian(data.AsSpan(blockOffset, 8));
            for (var index = 0; index < 16; index++)
            {
                alphaValues[index] = (byte)(((alphaBits >> (index * 4)) & 0x0F) * 17);
            }

            return alphaValues;
        }

        var alpha0 = data[blockOffset];
        var alpha1 = data[blockOffset + 1];
        Span<byte> table = stackalloc byte[8];
        table[0] = alpha0;
        table[1] = alpha1;
        if (alpha0 > alpha1)
        {
            for (var index = 2; index < 8; index++)
            {
                table[index] = (byte)(((8 - index) * alpha0 + (index - 1) * alpha1) / 7);
            }
        }
        else
        {
            for (var index = 2; index < 6; index++)
            {
                table[index] = (byte)(((6 - index) * alpha0 + (index - 1) * alpha1) / 5);
            }

            table[6] = 0;
            table[7] = 255;
        }

        ulong alphaBits48 = 0;
        for (var index = 0; index < 6; index++)
        {
            alphaBits48 |= (ulong)data[blockOffset + 2 + index] << (8 * index);
        }

        for (var index = 0; index < 16; index++)
        {
            alphaValues[index] = table[(int)((alphaBits48 >> (index * 3)) & 0x07)];
        }

        return alphaValues;
    }

    private static DdsColor[] BuildColorTable(ushort color0, ushort color1, bool forceFourColors)
    {
        var first = DecodeRgb565(color0, 255);
        var second = DecodeRgb565(color1, 255);
        var colors = new DdsColor[4];
        colors[0] = first;
        colors[1] = second;

        if (forceFourColors || color0 > color1)
        {
            colors[2] = Blend(first, second, 2, 1, 3, 255);
            colors[3] = Blend(first, second, 1, 2, 3, 255);
        }
        else
        {
            colors[2] = Blend(first, second, 1, 1, 2, 255);
            colors[3] = new DdsColor(0, 0, 0, 0);
        }

        return colors;
    }

    private static DdsColor DecodeRgb565(ushort value, byte alpha)
    {
        var red = (byte)((value >> 11) & 0x1F);
        var green = (byte)((value >> 5) & 0x3F);
        var blue = (byte)(value & 0x1F);
        return new DdsColor(
            (byte)((red << 3) | (red >> 2)),
            (byte)((green << 2) | (green >> 4)),
            (byte)((blue << 3) | (blue >> 2)),
            alpha);
    }

    private static DdsColor Blend(DdsColor a, DdsColor b, int aWeight, int bWeight, int divisor, byte alpha)
    {
        return new DdsColor(
            (byte)((a.Red * aWeight + b.Red * bWeight) / divisor),
            (byte)((a.Green * aWeight + b.Green * bWeight) / divisor),
            (byte)((a.Blue * aWeight + b.Blue * bWeight) / divisor),
            alpha);
    }

    private enum AlphaMode
    {
        None,
        Explicit,
        Interpolated
    }

    private readonly record struct DdsColor(byte Red, byte Green, byte Blue, byte Alpha);
}
