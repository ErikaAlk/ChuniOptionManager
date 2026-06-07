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

    public string DisplayDifficulty => Difficulty.Equals("ULTIMA", StringComparison.OrdinalIgnoreCase)
        ? "ULTIMA"
        : Difficulty;

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

        return new SolidColorBrush(key switch
        {
            "BASIC" => ColorHelper.FromArgb(255, 0, 169, 133),
            "ADVANCED" => ColorHelper.FromArgb(255, 249, 119, 0),
            "EXPERT" => ColorHelper.FromArgb(255, 224, 41, 41),
            "MASTER" => ColorHelper.FromArgb(255, 183, 0, 255),
            "ULTIMA" or "ULTRA" => Colors.Black,
            _ => ColorHelper.FromArgb(255, 72, 84, 102)
        });
    }

    public static Brush GetForeground(string difficulty)
    {
        var key = Normalize(difficulty);
        return new SolidColorBrush(key is "ADVANCED" ? Colors.Black : Colors.White);
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
}
