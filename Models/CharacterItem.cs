using ChuniOptionManager.Services;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace ChuniOptionManager.Models;

public sealed class CharacterItem
{
    private ImageSource? _bigImageSource;
    private ImageSource? _smallImageSource;
    private ImageSource? _thumbImageSource;
    private bool _bigImageLoaded;
    private bool _smallImageLoaded;
    private bool _thumbImageLoaded;

    public string Name { get; set; } = "";
    public string SortName { get; set; } = "";
    public string Works { get; set; } = "";
    public string IllustratorName { get; set; } = "";
    public string ExplainText { get; set; } = "";
    public string Package { get; set; } = "";
    public string DataName { get; set; } = "";
    public string ReleaseTag { get; set; } = "";
    public string NetOpenName { get; set; } = "";
    public string XmlPath { get; set; } = "";
    public string RelativePath { get; set; } = "";
    public string DdsXmlPath { get; set; } = "";
    public string DdsRelativePath { get; set; } = "";
    public string ImageKey { get; set; } = "";
    public string ImagePath { get; set; } = "";
    public string BigImagePath { get; set; } = "";
    public string SmallImagePath { get; set; } = "";
    public string ThumbImagePath { get; set; } = "";
    public int Id { get; set; }
    public int WorksId { get; set; }
    public int ReleaseTagId { get; set; }
    public int NetOpenId { get; set; }
    public int IllustratorId { get; set; }
    public bool DisableFlag { get; set; }
    public bool DefaultHave { get; set; }
    public int RareType { get; set; }
    public int Priority { get; set; }

    public ImageSource? ImageSource => BigImageSource;

    public ImageSource? BigImageSource
    {
        get
        {
            if (_bigImageLoaded)
            {
                return _bigImageSource;
            }

            _bigImageLoaded = true;
            _bigImageSource = LoadImage(BigImagePath);
            return _bigImageSource;
        }
    }

    public ImageSource? SmallImageSource
    {
        get
        {
            if (_smallImageLoaded)
            {
                return _smallImageSource;
            }

            _smallImageLoaded = true;
            _smallImageSource = LoadImage(SmallImagePath);
            return _smallImageSource;
        }
    }

    public ImageSource? ThumbImageSource
    {
        get
        {
            if (_thumbImageLoaded)
            {
                return _thumbImageSource;
            }

            _thumbImageLoaded = true;
            _thumbImageSource = LoadImage(ThumbImagePath);
            return _thumbImageSource;
        }
    }

    public bool Matches(string query)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return true;
        }

        return Name.Contains(query, StringComparison.CurrentCultureIgnoreCase)
            || Works.Contains(query, StringComparison.CurrentCultureIgnoreCase)
            || DataName.Contains(query, StringComparison.OrdinalIgnoreCase)
            || Id.ToString().Contains(query, StringComparison.OrdinalIgnoreCase);
    }

    private static ImageSource? LoadImage(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return null;
        }

        try
        {
            return new BitmapImage(new Uri(DdsPreviewCache.GetPreviewPath(path)));
        }
        catch
        {
            return null;
        }
    }
}
