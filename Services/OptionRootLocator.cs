namespace ChuniOptionManager.Services;

public static class OptionRootLocator
{
    private static readonly string[] MarkerDirectories = ["A001", "A300", "AXVX"];

    public static string FindDefaultRoot()
    {
        var candidates = new List<string>
        {
            Environment.CurrentDirectory,
            AppContext.BaseDirectory
        };

        var baseDirectory = new DirectoryInfo(AppContext.BaseDirectory);
        for (var current = baseDirectory; current is not null; current = current.Parent)
        {
            candidates.Add(current.FullName);
        }

        foreach (var candidate in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (LooksLikeOptionRoot(candidate))
            {
                return candidate;
            }
        }

        return Environment.CurrentDirectory;
    }

    public static bool LooksLikeOptionRoot(string path)
    {
        if (!Directory.Exists(path))
        {
            return false;
        }

        return MarkerDirectories.Count(marker => Directory.Exists(Path.Combine(path, marker))) >= 2
            && Directory.EnumerateFiles(path, "Music.xml", SearchOption.AllDirectories).Any();
    }
}
