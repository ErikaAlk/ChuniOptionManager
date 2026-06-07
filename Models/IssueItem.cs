namespace ChuniOptionManager.Models;

public sealed class IssueItem
{
    public string Severity { get; set; } = "Info";
    public string Title { get; set; } = "";
    public string Detail { get; set; } = "";
    public string Path { get; set; } = "";
}

public sealed class OptionCatalog
{
    public List<MusicItem> Songs { get; set; } = [];
    public List<CharacterItem> Characters { get; set; } = [];
    public List<IssueItem> Issues { get; set; } = [];
}
