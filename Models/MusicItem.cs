using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace ChuniOptionManager.Models;

public sealed class MusicItem
{
    private ImageSource? _jacketSource;
    private bool _jacketLoaded;

    public string Title { get; set; } = "";
    public string SortTitle { get; set; } = "";
    public string Artist { get; set; } = "";
    public string Genre { get; set; } = "";
    public string Works { get; set; } = "";
    public string Package { get; set; } = "";
    public string DataName { get; set; } = "";
    public string ReleaseTag { get; set; } = "";
    public string XmlPath { get; set; } = "";
    public string RelativePath { get; set; } = "";
    public string JacketPath { get; set; } = "";
    public int Id { get; set; }
    public bool DisableFlag { get; set; }
    public bool EnableUltima { get; set; }
    public List<ChartModel> Charts { get; set; } = [];

    public IEnumerable<ChartModel> EnabledCharts => Charts.Where(chart => chart.IsEnabled);
    public IEnumerable<ChartModel> ExistingEnabledCharts => Charts.Where(chart => chart.IsEnabled && chart.FileExists);
    public bool HasMissingEnabledFile => Charts.Any(chart => chart.IsEnabled && !chart.FileExists);
    public bool HasPartialNormalSet => !HasNormalFour && EnabledCharts.Any(chart => chart.Difficulty != "WORLD'S END");
    public bool HasNormalFour => HasEnabled("BASIC") && HasEnabled("ADVANCED") && HasEnabled("EXPERT") && HasEnabled("MASTER");

    public ChartModel? PrimaryChart
    {
        get
        {
            return ExistingEnabledCharts
                .OrderByDescending(chart => DifficultyPalette.Rank(chart.Difficulty))
                .ThenByDescending(chart => chart.Level)
                .FirstOrDefault()
                ?? EnabledCharts.OrderByDescending(chart => DifficultyPalette.Rank(chart.Difficulty)).FirstOrDefault()
                ?? Charts.OrderByDescending(chart => DifficultyPalette.Rank(chart.Difficulty)).FirstOrDefault();
        }
    }

    public string PrimaryDifficulty => PrimaryChart?.DisplayDifficulty ?? "NO DATA";
    public string PrimaryLevel => PrimaryChart?.LevelText ?? "-";
    public Brush PrimaryBrush => PrimaryChart?.DifficultyBrush ?? DifficultyPalette.GetBrush("");
    public Brush PrimaryForeground => PrimaryChart?.DifficultyForeground ?? DifficultyPalette.GetForeground("");
    public string DifficultySummary => string.Join(" / ", EnabledCharts.Select(chart => chart.DisplayDifficulty));
    public string CardSubText => string.IsNullOrWhiteSpace(Artist) ? Package : Artist;

    public ImageSource? JacketSource
    {
        get
        {
            if (_jacketLoaded)
            {
                return _jacketSource;
            }

            _jacketLoaded = true;
            if (!string.IsNullOrWhiteSpace(JacketPath) && File.Exists(JacketPath))
            {
                try
                {
                    _jacketSource = new BitmapImage(new Uri(JacketPath));
                }
                catch
                {
                    _jacketSource = null;
                }
            }

            return _jacketSource;
        }
    }

    public bool Matches(string query)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return true;
        }

        return Contains(Title, query)
            || Contains(Artist, query)
            || Contains(Genre, query)
            || Contains(Works, query)
            || Contains(DataName, query)
            || Id.ToString().Contains(query, StringComparison.OrdinalIgnoreCase);
    }

    public bool HasEnabled(string difficulty)
    {
        return EnabledCharts.Any(chart => chart.Difficulty.Equals(difficulty, StringComparison.OrdinalIgnoreCase));
    }

    private static bool Contains(string source, string query)
    {
        return source.Contains(query, StringComparison.CurrentCultureIgnoreCase);
    }
}
