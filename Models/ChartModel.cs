using System.ComponentModel;
using System.Runtime.CompilerServices;
using Microsoft.UI;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;

namespace ChuniOptionManager.Models;

public sealed class ChartModel : INotifyPropertyChanged
{
    private bool _isEnabled;

    public int Index { get; set; }
    public string Difficulty { get; set; } = "";
    public string FileName { get; set; } = "";
    public string FullPath { get; set; } = "";
    public int Level { get; set; }
    public int LevelDecimal { get; set; }
    public bool FileExists { get; set; }
    public string NotesDesigner { get; set; } = "";

    public bool IsEnabled
    {
        get => _isEnabled;
        set
        {
            if (_isEnabled == value)
            {
                return;
            }

            _isEnabled = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(StateText));
            OnPropertyChanged(nameof(ProblemText));
        }
    }

    // Difficulty 在解析时已被 NormalizeDifficulty 归一成大写规范值（含 ULTRA→ULTIMA），这里直接返回即可。
    public string DisplayDifficulty => Difficulty;

    public string LevelText
    {
        get
        {
            if (Level <= 0)
            {
                return "-";
            }

            return LevelDecimal > 0 ? $"{Level}.{LevelDecimal / 10}" : Level.ToString();
        }
    }

    public string StateText => IsEnabled ? "启用" : "关闭";

    public string ProblemText
    {
        get
        {
            if (IsEnabled && !FileExists)
            {
                return "启用但文件缺失";
            }

            if (!IsEnabled && FileExists)
            {
                return "文件存在但未启用";
            }

            return FileExists ? "文件正常" : "无谱面文件";
        }
    }

    public Brush DifficultyBrush => DifficultyPalette.GetBrush(Difficulty);
    public Brush DifficultyForeground => DifficultyPalette.GetForeground(Difficulty);

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public static class DifficultyPalette
{
    public static Brush GetBrush(string difficulty)
    {
        var key = Normalize(difficulty);
        if (key == "WORLD'S END" || key == "WORLDSEND")
        {
            return BrushCache.WorldsEnd;
        }

        return key switch
        {
            "BASIC" => BrushCache.Basic,
            "ADVANCED" => BrushCache.Advanced,
            "EXPERT" => BrushCache.Expert,
            "MASTER" => BrushCache.Master,
            "ULTIMA" or "ULTRA" => BrushCache.Ultima,
            _ => BrushCache.Default
        };
    }

    public static Brush GetForeground(string difficulty)
    {
        return Normalize(difficulty) is "ADVANCED" ? BrushCache.BlackForeground : BrushCache.WhiteForeground;
    }

    public static int Rank(string difficulty)
    {
        return Normalize(difficulty) switch
        {
            "BASIC" => 0,
            "ADVANCED" => 1,
            "EXPERT" => 2,
            "MASTER" => 3,
            "ULTIMA" or "ULTRA" => 4,
            "WORLD'S END" or "WORLDSEND" => 5,
            _ => -1
        };
    }

    private static string Normalize(string difficulty)
    {
        return difficulty.Trim().ToUpperInvariant().Replace("WORLD'SEND", "WORLD'S END");
    }

    // 难度配色是纯函数（只取决于难度字符串），整个程序共用一组不可变画刷即可，
    // 不必每次数据绑定都 new 一把：一张歌曲卡要读 10+ 次画刷，上千张卡 × 每次筛选会产生上万个临时画刷。
    // 放进嵌套类延迟初始化，保证画刷在首次绑定（UI 线程）时才创建——Rank 在后台扫描线程被调用，不会触碰这里。
    private static class BrushCache
    {
        internal static readonly Brush Basic = Solid(0, 169, 133);
        internal static readonly Brush Advanced = Solid(249, 119, 0);
        internal static readonly Brush Expert = Solid(224, 41, 41);
        internal static readonly Brush Master = Solid(183, 0, 255);
        internal static readonly Brush Ultima = new SolidColorBrush(Colors.Black);
        internal static readonly Brush Default = Solid(72, 84, 102);
        internal static readonly Brush WhiteForeground = new SolidColorBrush(Colors.White);
        internal static readonly Brush BlackForeground = new SolidColorBrush(Colors.Black);
        internal static readonly Brush WorldsEnd = CreateWorldsEndBrush();

        private static SolidColorBrush Solid(byte r, byte g, byte b)
        {
            return new SolidColorBrush(ColorHelper.FromArgb(255, r, g, b));
        }

        private static Brush CreateWorldsEndBrush()
        {
            return new LinearGradientBrush
            {
                StartPoint = new Point(0, 0.5),
                EndPoint = new Point(1, 0.5),
                GradientStops =
                {
                    new GradientStop { Color = ColorHelper.FromArgb(255, 255, 44, 76), Offset = 0.00 },
                    new GradientStop { Color = ColorHelper.FromArgb(255, 255, 186, 0), Offset = 0.20 },
                    new GradientStop { Color = ColorHelper.FromArgb(255, 0, 180, 110), Offset = 0.40 },
                    new GradientStop { Color = ColorHelper.FromArgb(255, 0, 168, 255), Offset = 0.62 },
                    new GradientStop { Color = ColorHelper.FromArgb(255, 146, 68, 255), Offset = 0.82 },
                    new GradientStop { Color = ColorHelper.FromArgb(255, 255, 70, 210), Offset = 1.00 }
                }
            };
        }
    }
}
