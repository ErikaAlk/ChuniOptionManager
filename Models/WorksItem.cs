namespace ChuniOptionManager.Models;

public sealed class WorksItem
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public string SortName { get; set; } = "";
    public int Priority { get; set; }
    public string Package { get; set; } = "";
    public string XmlPath { get; set; } = "";
    public string RelativePath { get; set; } = "";

    public string Display => $"{Name}（{Id}）";
}
