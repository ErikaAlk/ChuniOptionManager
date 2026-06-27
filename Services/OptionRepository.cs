using System.Xml.Linq;
using System.Xml;
using ChuniOptionManager.Models;

namespace ChuniOptionManager.Services;

public static class OptionRepository
{
    private const int DefaultCustomCharacterPriority = 999;
    private const string DefaultCustomCharacterPackage = "AZUR";
    private const string DeletedItemsFolder = "_deleted";
    public const int DefaultAzurWorksId = 11451;

    public static OptionCatalog Scan(string optionRoot)
    {
        var root = Path.GetFullPath(optionRoot);
        var ddsIndex = BuildDdsImageIndex(root);
        var songs = Directory.EnumerateFiles(root, "Music.xml", SearchOption.AllDirectories)
            .Where(path => !IsDeletedPath(root, path))
            .Select(path => ParseMusic(root, path))
            .Where(item => item is not null)
            .Cast<MusicItem>()
            .OrderBy(item => item.SortTitle)
            .ThenBy(item => item.Id)
            .ToList();

        var characters = Directory.EnumerateFiles(root, "Chara.xml", SearchOption.AllDirectories)
            .Where(path => !IsDeletedPath(root, path))
            .Select(path => ParseCharacter(root, path, ddsIndex))
            .Where(item => item is not null)
            .Cast<CharacterItem>()
            .OrderBy(item => item.SortName)
            .ThenBy(item => item.Id)
            .ToList();

        return new OptionCatalog
        {
            Songs = songs,
            Characters = characters,
            Issues = BuildIssues(songs, characters)
        };
    }

    public static void SaveChartEnableStates(MusicItem music)
    {
        var document = XDocument.Load(music.XmlPath, LoadOptions.PreserveWhitespace);
        var fumenNodes = document.Root?
            .Element("fumens")?
            .Elements("MusicFumenData")
            .ToList() ?? [];

        foreach (var chart in music.Charts)
        {
            if (chart.Index < 0 || chart.Index >= fumenNodes.Count)
            {
                continue;
            }

            var enableNode = fumenNodes[chart.Index].Element("enable");
            if (enableNode is null)
            {
                fumenNodes[chart.Index].Add(new XElement("enable", chart.IsEnabled ? "true" : "false"));
            }
            else
            {
                enableNode.Value = chart.IsEnabled ? "true" : "false";
            }
        }

        EnsureBackup(music.XmlPath);
        document.Save(music.XmlPath, SaveOptions.DisableFormatting);
    }

    public static void SaveCharacterSettings(CharacterItem character)
    {
        if (string.IsNullOrWhiteSpace(character.XmlPath) || !File.Exists(character.XmlPath))
        {
            throw new FileNotFoundException("找不到角色 Chara.xml。", character.XmlPath);
        }

        var document = XDocument.Load(character.XmlPath, LoadOptions.PreserveWhitespace);
        var charaRoot = document.Root ?? throw new InvalidOperationException("Chara.xml 没有根节点。");

        SetText(charaRoot, "disableFlag", BoolText(character.DisableFlag));
        SetText(charaRoot, "name", "str", character.Name.Trim());
        SetText(charaRoot, "sortName", string.IsNullOrWhiteSpace(character.SortName) ? character.Name.Trim() : character.SortName.Trim());
        SetText(charaRoot, "works", "id", character.WorksId.ToString());
        SetText(charaRoot, "works", "str", character.Works.Trim());
        SetText(charaRoot, "defaultHave", BoolText(character.DefaultHave));
        SetText(charaRoot, "rareType", character.RareType.ToString());
        SetText(charaRoot, "priority", character.Priority.ToString());
        SetText(charaRoot, "releaseTagName", "id", character.ReleaseTagId.ToString());
        SetText(charaRoot, "releaseTagName", "str", character.ReleaseTag.Trim());
        SetText(charaRoot, "netOpenName", "id", character.NetOpenId.ToString());
        SetText(charaRoot, "netOpenName", "str", character.NetOpenName.Trim());
        SetText(charaRoot, "illustratorName", "id", character.IllustratorId.ToString());
        SetText(charaRoot, "illustratorName", "str", character.IllustratorName.Trim());
        SetText(charaRoot, "explainText", character.ExplainText.Trim());

        EnsureBackup(character.XmlPath);
        SaveXml(document, character.XmlPath);
    }

    public static string DeleteMusic(string optionRoot, MusicItem music)
    {
        var musicDirectory = Path.GetDirectoryName(music.XmlPath);
        if (string.IsNullOrWhiteSpace(musicDirectory) || !Directory.Exists(musicDirectory))
        {
            throw new DirectoryNotFoundException($"找不到歌曲目录：{music.XmlPath}");
        }

        return MoveToDeleted(optionRoot, "song", music.Id, music.Title, [musicDirectory]);
    }

    public static string DeleteCharacter(string optionRoot, CharacterItem character)
    {
        var root = Path.GetFullPath(optionRoot);
        var directories = new List<string>();
        var charaDirectory = Path.GetDirectoryName(character.XmlPath);
        if (!string.IsNullOrWhiteSpace(charaDirectory))
        {
            directories.Add(charaDirectory);
        }

        var ddsDirectory = Path.GetDirectoryName(character.DdsXmlPath);
        // 只有当 DDSImage 目录和角色在同一个包里时才一并删除：跨包"借用"的贴图目录可能被别的角色共用，删了会误伤。
        if (!string.IsNullOrWhiteSpace(ddsDirectory) && IsSamePackage(root, character.XmlPath, character.DdsXmlPath))
        {
            directories.Add(ddsDirectory);
        }

        return MoveToDeleted(optionRoot, "character", character.Id, character.Name, directories);
    }

    public static int AddCharacter(string optionRoot, AddCharacterRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.Name))
        {
            throw new InvalidOperationException("角色名不能为空。");
        }

        var root = Path.GetFullPath(optionRoot);
        var packageRoot = Path.Combine(root, DefaultCustomCharacterPackage);
        var charaRoot = Path.Combine(packageRoot, "chara");
        var ddsRoot = Path.Combine(packageRoot, "ddsImage");
        var worksRoot = Path.Combine(packageRoot, "charaWorks");

        if (!Directory.Exists(packageRoot))
        {
            throw new DirectoryNotFoundException($"找不到模板包目录：{packageRoot}");
        }

        var templateCharaPath = ResolveTemplateCharaPath(charaRoot);
        var templateDdsPath = ResolveTemplateDdsPath(ddsRoot);
        // 指定了 ID 就校验后用它（撞号/目录占用会抛错）；否则自动分配下一个空闲 id。
        var newId = request.Id > 0
            ? ValidateExplicitCharacterId(root, charaRoot, request.Id)
            : NextCustomCharacterId(root, charaRoot);
        var sortName = string.IsNullOrWhiteSpace(request.SortName) ? request.Name.Trim() : request.SortName.Trim();
        var charaImageKey = $"chara{newId}_00";
        var addImageKey = $"chara{newId}_01";

        var newCharaDirectory = Path.Combine(charaRoot, $"chara{newId}");
        var newDdsDirectory = Path.Combine(ddsRoot, $"ddsImage{newId}");
        var charaDirectoryCreated = !Directory.Exists(newCharaDirectory);
        var ddsDirectoryCreated = !Directory.Exists(newDdsDirectory);
        Directory.CreateDirectory(newCharaDirectory);
        Directory.CreateDirectory(newDdsDirectory);

        try
        {
            var charaDocument = XDocument.Load(templateCharaPath);
            var chara = charaDocument.Root ?? throw new InvalidOperationException("模板 Chara.xml 无根节点。");
            SetText(chara, "dataName", $"chara{newId}");
            SetText(chara, "name", "id", newId.ToString());
            SetText(chara, "name", "str", request.Name.Trim());
            SetText(chara, "sortName", sortName);
            SetText(chara, "defaultImages", "id", newId.ToString());
            SetText(chara, "defaultImages", "str", charaImageKey);
            SetText(chara, "addImages1", "charaName", "id", (newId + 100000).ToString());
            SetText(chara, "addImages1", "charaName", "str", request.Name.Trim());
            SetText(chara, "addImages1", "image", "id", (newId + 100000).ToString());
            SetText(chara, "addImages1", "image", "str", addImageKey);
            SetText(chara, "works", "id", request.WorksId.ToString());
            SetText(chara, "works", "str", request.WorksName.Trim());
            SetText(chara, "priority", DefaultCustomCharacterPriority.ToString());
            if (!string.IsNullOrWhiteSpace(request.IllustratorName))
            {
                SetText(chara, "illustratorName", "str", request.IllustratorName.Trim());
            }
            SaveXml(charaDocument, Path.Combine(newCharaDirectory, "Chara.xml"));

            var ddsDocument = XDocument.Load(templateDdsPath);
            var dds = ddsDocument.Root ?? throw new InvalidOperationException("模板 DDSImage.xml 无根节点。");
            SetText(dds, "dataName", $"ddsImage{newId}");
            SetText(dds, "name", "id", newId.ToString());
            SetText(dds, "name", "str", charaImageKey);
            SetText(dds, "ddsFile0", "path", "big.dds");
            SetText(dds, "ddsFile1", "path", "small.dds");
            SetText(dds, "ddsFile2", "path", "thumb.dds");
            SaveXml(ddsDocument, Path.Combine(newDdsDirectory, "DDSImage.xml"));

            if (!string.IsNullOrWhiteSpace(request.SourceImagePath))
            {
                DdsImageGenerator.GenerateCharacterDds(request.SourceImagePath, newDdsDirectory, request.Crops);
            }

            if (request.WorksId > 0 && EnsureWorksPriority(worksRoot, request.WorksId))
            {
                AddWorksToSortFirst(Path.Combine(worksRoot, "WorksSort.xml"), request.WorksId);
            }
        }
        catch
        {
            // 半途失败（如源图损坏、DDS 生成抛错）就回滚我们刚建的目录，
            // 避免在 option 树里留下没有贴图的残缺角色，并把这个 id 永久占用。
            if (charaDirectoryCreated)
            {
                TryDeleteDirectory(newCharaDirectory);
            }

            if (ddsDirectoryCreated)
            {
                TryDeleteDirectory(newDdsDirectory);
            }

            throw;
        }

        return newId;
    }

    public static List<WorksItem> ListWorks(string optionRoot)
    {
        var root = Path.GetFullPath(optionRoot);
        var list = new List<WorksItem>();

        foreach (var path in Directory.EnumerateFiles(root, "CharaWorks.xml", SearchOption.AllDirectories))
        {
            if (IsDeletedPath(root, path))
            {
                continue;
            }

            try
            {
                var document = XDocument.Load(path);
                var worksRoot = document.Root;
                if (worksRoot is null)
                {
                    continue;
                }

                list.Add(new WorksItem
                {
                    Id = Int(worksRoot.Element("name"), "id"),
                    Name = Text(worksRoot, "name", "str"),
                    SortName = Text(worksRoot, "sortName"),
                    Priority = Int(worksRoot, "priority"),
                    Package = PackageName(root, path),
                    XmlPath = path,
                    RelativePath = Path.GetRelativePath(root, path)
                });
            }
            catch
            {
                // Bad custom XML should not break the works list.
            }
        }

        return list
            .OrderBy(works => works.Id)
            .ThenBy(works => works.Package, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public static List<string> ListWorksPackages(string optionRoot)
    {
        var root = Path.GetFullPath(optionRoot);
        if (!Directory.Exists(root))
        {
            return [];
        }

        return Directory.EnumerateDirectories(root)
            .Select(path => Path.GetFileName(path) ?? "")
            .Where(name => !string.IsNullOrWhiteSpace(name)
                && !name.Equals(DeletedItemsFolder, StringComparison.OrdinalIgnoreCase)
                && !name.StartsWith('.'))
            .OrderByDescending(name => name.Equals(DefaultCustomCharacterPackage, StringComparison.OrdinalIgnoreCase))
            .ThenBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public static WorksItem AddWorks(string optionRoot, string package, int id, string name, string sortName)
    {
        if (id <= 0)
        {
            throw new InvalidOperationException("作品 ID 必须是正整数。");
        }

        if (string.IsNullOrWhiteSpace(name))
        {
            throw new InvalidOperationException("作品名不能为空。");
        }

        if (string.IsNullOrWhiteSpace(package))
        {
            throw new InvalidOperationException("请选择写入的包目录。");
        }

        var root = Path.GetFullPath(optionRoot);
        var packageRoot = Path.Combine(root, package);
        if (!Directory.Exists(packageRoot))
        {
            throw new DirectoryNotFoundException($"找不到包目录：{packageRoot}");
        }

        if (ListWorks(root).Any(works => works.Id == id))
        {
            throw new InvalidOperationException($"作品 ID {id} 已存在，请换一个。");
        }

        var worksRoot = Path.Combine(packageRoot, "charaWorks");
        var dataName = $"charaWorks{id:D6}";
        var directory = Path.Combine(worksRoot, dataName);
        if (Directory.Exists(directory))
        {
            throw new InvalidOperationException($"目录已存在：{directory}");
        }

        var effectiveSortName = string.IsNullOrWhiteSpace(sortName) ? name.Trim() : sortName.Trim();
        var document = XDocument.Load(ResolveTemplateWorksPath(root, worksRoot));
        var worksDoc = document.Root ?? throw new InvalidOperationException("模板 CharaWorks.xml 无根节点。");
        SetText(worksDoc, "dataName", dataName);
        SetText(worksDoc, "name", "id", id.ToString());
        SetText(worksDoc, "name", "str", name.Trim());
        SetText(worksDoc, "sortName", effectiveSortName);
        SetText(worksDoc, "priority", DefaultCustomCharacterPriority.ToString());

        Directory.CreateDirectory(directory);
        var xmlPath = Path.Combine(directory, "CharaWorks.xml");
        SaveXml(document, xmlPath);
        AddWorksToSortFirst(Path.Combine(worksRoot, "WorksSort.xml"), id);

        return new WorksItem
        {
            Id = id,
            Name = name.Trim(),
            SortName = effectiveSortName,
            Priority = DefaultCustomCharacterPriority,
            Package = package,
            XmlPath = xmlPath,
            RelativePath = Path.GetRelativePath(root, xmlPath)
        };
    }

    public static void UpdateWorks(WorksItem works)
    {
        if (string.IsNullOrWhiteSpace(works.XmlPath) || !File.Exists(works.XmlPath))
        {
            throw new FileNotFoundException("找不到作品 CharaWorks.xml。", works.XmlPath);
        }

        var document = XDocument.Load(works.XmlPath);
        var worksRoot = document.Root ?? throw new InvalidOperationException("CharaWorks.xml 无根节点。");
        SetText(worksRoot, "name", "str", works.Name.Trim());
        SetText(worksRoot, "sortName", string.IsNullOrWhiteSpace(works.SortName) ? works.Name.Trim() : works.SortName.Trim());
        SetText(worksRoot, "priority", works.Priority.ToString());

        EnsureBackup(works.XmlPath);
        SaveXml(document, works.XmlPath);
    }

    public static string DeleteWorks(string optionRoot, WorksItem works)
    {
        var directory = Path.GetDirectoryName(works.XmlPath);
        if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
        {
            throw new DirectoryNotFoundException($"找不到作品目录：{works.XmlPath}");
        }

        var root = Path.GetFullPath(optionRoot);
        var charaWorksRoot = Path.GetDirectoryName(directory);
        if (!string.IsNullOrWhiteSpace(charaWorksRoot))
        {
            RemoveWorksFromSort(Path.Combine(charaWorksRoot, "WorksSort.xml"), works.Id);
        }

        var directories = new List<string> { directory };

        // 连带删除属于该作品的角色（含其 Chara 目录与匹配到的 DDSImage 目录）。
        // works.Id 必须有效（>0）：id=0 代表"无作品/解析失败"，若放任 cascade 会把所有 worksId 缺失的角色一起误删。
        if (works.Id > 0)
        {
            foreach (var character in Scan(root).Characters.Where(item => item.WorksId == works.Id))
            {
                var charaDirectory = Path.GetDirectoryName(character.XmlPath);
                if (!string.IsNullOrWhiteSpace(charaDirectory))
                {
                    directories.Add(charaDirectory);
                }

                var ddsDirectory = Path.GetDirectoryName(character.DdsXmlPath);
                // 同上：跨包借用的 DDSImage 目录不连带删除，避免误伤其它角色。
                if (!string.IsNullOrWhiteSpace(ddsDirectory) && IsSamePackage(root, character.XmlPath, character.DdsXmlPath))
                {
                    directories.Add(ddsDirectory);
                }
            }
        }

        return MoveToDeleted(optionRoot, "works", works.Id, works.Name, directories);
    }

    private static Dictionary<string, List<DdsImageInfo>> BuildDdsImageIndex(string root)
    {
        var index = new Dictionary<string, List<DdsImageInfo>>(StringComparer.OrdinalIgnoreCase);

        foreach (var path in Directory.EnumerateFiles(root, "DDSImage.xml", SearchOption.AllDirectories))
        {
            try
            {
                if (IsDeletedPath(root, path))
                {
                    continue;
                }

                var document = XDocument.Load(path);
                var imageKey = Text(document.Root, "name", "str");
                if (string.IsNullOrWhiteSpace(imageKey))
                {
                    continue;
                }

                if (!index.TryGetValue(imageKey, out var images))
                {
                    images = [];
                    index[imageKey] = images;
                }

                var directory = Path.GetDirectoryName(path) ?? root;
                images.Add(new DdsImageInfo(
                    PackageName(root, path),
                    path,
                    Path.GetRelativePath(root, path),
                    ResolveDdsPath(directory, Text(document.Root, "ddsFile0", "path")),
                    ResolveDdsPath(directory, Text(document.Root, "ddsFile1", "path")),
                    ResolveDdsPath(directory, Text(document.Root, "ddsFile2", "path"))));
            }
            catch
            {
                // Bad custom XML should not prevent the catalog from opening.
            }
        }

        return index;
    }

    private static MusicItem? ParseMusic(string root, string path)
    {
        try
        {
            var document = XDocument.Load(path);
            var musicRoot = document.Root;
            if (musicRoot is null)
            {
                return null;
            }

            var directory = Path.GetDirectoryName(path) ?? root;
            var jacketFile = Text(musicRoot, "jaketFile", "path");
            var chartNodes = musicRoot.Element("fumens")?.Elements("MusicFumenData").ToList() ?? [];
            var charts = new List<ChartModel>();

            for (var index = 0; index < chartNodes.Count; index++)
            {
                var node = chartNodes[index];
                var fileName = Text(node, "file", "path");
                var fullPath = string.IsNullOrWhiteSpace(fileName) ? "" : Path.Combine(directory, fileName);
                var difficulty = Text(node, "type", "data");
                if (string.IsNullOrWhiteSpace(difficulty))
                {
                    difficulty = Text(node, "type", "str");
                }

                charts.Add(new ChartModel
                {
                    Index = index,
                    Difficulty = NormalizeDifficulty(difficulty),
                    IsEnabled = Bool(node, "enable"),
                    FileName = fileName,
                    FullPath = fullPath,
                    FileExists = !string.IsNullOrWhiteSpace(fullPath) && File.Exists(fullPath),
                    Level = Int(node, "level"),
                    LevelDecimal = Int(node, "levelDecimal"),
                    NotesDesigner = Text(node, "notesDesigner")
                });
            }

            return new MusicItem
            {
                Title = Text(musicRoot, "name", "str"),
                SortTitle = Text(musicRoot, "sortName"),
                Artist = Text(musicRoot, "artistName", "str"),
                Genre = string.Join(", ", musicRoot.Element("genreNames")?.Element("list")?.Elements("StringID").Select(item => Text(item, "str")) ?? []),
                Works = Text(musicRoot, "worksName", "str"),
                Package = PackageName(root, path),
                DataName = Text(musicRoot, "dataName"),
                ReleaseTag = Text(musicRoot, "releaseTagName", "str"),
                XmlPath = path,
                RelativePath = Path.GetRelativePath(root, path),
                JacketPath = string.IsNullOrWhiteSpace(jacketFile) ? "" : Path.Combine(directory, jacketFile),
                Id = Int(musicRoot.Element("name"), "id"),
                DisableFlag = Bool(musicRoot, "disableFlag"),
                EnableUltima = Bool(musicRoot, "enableUltima"),
                Charts = charts
            };
        }
        catch
        {
            return null;
        }
    }

    private static CharacterItem? ParseCharacter(string root, string path, IReadOnlyDictionary<string, List<DdsImageInfo>> ddsIndex)
    {
        try
        {
            var document = XDocument.Load(path);
            var charaRoot = document.Root;
            if (charaRoot is null)
            {
                return null;
            }

            var imageKey = Text(charaRoot, "defaultImages", "str");
            var package = PackageName(root, path);
            var imageInfo = ResolveDdsImage(ddsIndex, imageKey, package);
            var bigImagePath = imageInfo?.BigPath ?? "";

            return new CharacterItem
            {
                Name = Text(charaRoot, "name", "str"),
                SortName = Text(charaRoot, "sortName"),
                Works = Text(charaRoot, "works", "str"),
                IllustratorName = Text(charaRoot, "illustratorName", "str"),
                ExplainText = Text(charaRoot, "explainText"),
                Package = package,
                DataName = Text(charaRoot, "dataName"),
                ReleaseTag = Text(charaRoot, "releaseTagName", "str"),
                NetOpenName = Text(charaRoot, "netOpenName", "str"),
                XmlPath = path,
                RelativePath = Path.GetRelativePath(root, path),
                DdsXmlPath = imageInfo?.XmlPath ?? "",
                DdsRelativePath = imageInfo?.RelativePath ?? "",
                ImageKey = imageKey,
                ImagePath = bigImagePath,
                BigImagePath = bigImagePath,
                SmallImagePath = imageInfo?.SmallPath ?? "",
                ThumbImagePath = imageInfo?.ThumbPath ?? "",
                Id = Int(charaRoot.Element("name"), "id"),
                WorksId = Int(charaRoot.Element("works"), "id"),
                ReleaseTagId = Int(charaRoot.Element("releaseTagName"), "id"),
                NetOpenId = Int(charaRoot.Element("netOpenName"), "id"),
                IllustratorId = Int(charaRoot.Element("illustratorName"), "id"),
                DisableFlag = Bool(charaRoot, "disableFlag"),
                DefaultHave = Bool(charaRoot, "defaultHave"),
                RareType = Int(charaRoot, "rareType"),
                Priority = Int(charaRoot, "priority")
            };
        }
        catch
        {
            return null;
        }
    }

    private static List<IssueItem> BuildIssues(IReadOnlyList<MusicItem> songs, IReadOnlyList<CharacterItem> characters)
    {
        var issues = new List<IssueItem>();

        foreach (var song in songs)
        {
            var missingCharts = song.Charts
                .Where(chart => chart.IsEnabled && !chart.FileExists)
                .OrderBy(chart => DifficultyPalette.Rank(chart.Difficulty))
                .ToList();

            if (missingCharts.Count == 0)
            {
                continue;
            }

            issues.Add(new IssueItem
            {
                Severity = "High",
                Title = $"{song.Title} 缺少 {string.Join(", ", missingCharts.Select(chart => chart.DisplayDifficulty))}",
                Detail = $"XML 已启用，但找不到谱面文件：{string.Join("、", missingCharts.Select(chart => chart.FileName))}",
                Path = song.RelativePath
            });
        }

        // 只对有效 ID（>0）做重复项比对：id=0 代表 name/id 缺失或非数字，把它们归成一组会产生大量虚假"重复"告警。
        foreach (var group in songs.GroupBy(song => song.Id).Where(group => group.Key > 0 && group.Count() > 1))
        {
            var difficultySets = group
                .Select(song => string.Join(",", song.ExistingEnabledCharts.Select(chart => chart.Difficulty).OrderBy(item => item)))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();

            if (difficultySets.Count <= 1)
            {
                continue;
            }

            var union = group
                .SelectMany(song => song.ExistingEnabledCharts.Select(chart => chart.Difficulty))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(DifficultyPalette.Rank)
                .ToList();

            foreach (var song in group)
            {
                var missing = union
                    .Where(difficulty => !song.ExistingEnabledCharts.Any(chart => chart.Difficulty.Equals(difficulty, StringComparison.OrdinalIgnoreCase)))
                    .ToList();

                if (missing.Count == 0)
                {
                    continue;
                }

                issues.Add(new IssueItem
                {
                    Severity = "Medium",
                    Title = $"{song.Title} 重复项少难度",
                    Detail = $"{song.Package}/{song.DataName} 缺少 {string.Join(", ", missing)}",
                    Path = song.RelativePath
                });
            }
        }

        foreach (var character in characters.Where(item => string.IsNullOrWhiteSpace(item.ImagePath) || !File.Exists(item.ImagePath)))
        {
            issues.Add(new IssueItem
            {
                Severity = "Low",
                Title = $"{character.Name} 缺少角色图索引",
                Detail = $"defaultImages={character.ImageKey}",
                Path = character.RelativePath
            });
        }

        return issues
            .OrderBy(issue => issue.Severity switch { "High" => 0, "Medium" => 1, "Low" => 2, _ => 3 })
            .ThenBy(issue => issue.Title)
            .ToList();
    }

    private static string Text(XElement? element, params string[] names)
    {
        var current = element;
        foreach (var name in names)
        {
            current = current?.Element(name);
        }

        return current?.Value.Trim() ?? "";
    }

    private static bool Bool(XElement? element, string name)
    {
        return bool.TryParse(Text(element, name), out var value) && value;
    }

    private static int Int(XElement? element, string name)
    {
        return int.TryParse(Text(element, name), out var value) ? value : 0;
    }

    private static string PackageName(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        var separators = new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar };
        return relative.Split(separators, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "";
    }

    private static string ResolveDdsPath(string directory, string path)
    {
        return string.IsNullOrWhiteSpace(path) ? "" : Path.Combine(directory, path);
    }

    private static DdsImageInfo? ResolveDdsImage(IReadOnlyDictionary<string, List<DdsImageInfo>> index, string imageKey, string package)
    {
        if (!index.TryGetValue(imageKey, out var images) || images.Count == 0)
        {
            return null;
        }

        return images.FirstOrDefault(image => image.Package.Equals(package, StringComparison.OrdinalIgnoreCase))
            ?? images.FirstOrDefault();
    }

    private static bool IsDeletedPath(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        var separators = new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar };
        return relative
            .Split(separators, StringSplitOptions.RemoveEmptyEntries)
            .Any(part => part.Equals(DeletedItemsFolder, StringComparison.OrdinalIgnoreCase));
    }

    private static string MoveToDeleted(string optionRoot, string type, int id, string name, IEnumerable<string> sourceDirectories)
    {
        var root = Path.GetFullPath(optionRoot);
        var sources = sourceDirectories
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Select(Path.GetFullPath)
            .Where(Directory.Exists)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (sources.Count == 0)
        {
            throw new DirectoryNotFoundException("找不到可删除的目录。");
        }

        foreach (var source in sources)
        {
            EnsureInsideOptionRoot(root, source);
            if (source.Equals(root, StringComparison.OrdinalIgnoreCase) || IsDeletedPath(root, source))
            {
                throw new InvalidOperationException($"不允许移动该目录：{source}");
            }
        }

        var deletedRoot = Path.Combine(root, DeletedItemsFolder);
        Directory.CreateDirectory(deletedRoot);

        // 归档目录名只精确到秒：同一秒内删除两个同类型/同 id/同名的条目会撞名，
        // 进而让后续 Directory.Move 合并或抛异常。撞名就追加序号，保证每次删除拿到独立目录。
        var archiveBaseName = $"{DateTime.Now:yyyyMMdd_HHmmss}_{type}_{id}_{SafeFileName(name)}";
        var archiveRoot = Path.Combine(deletedRoot, archiveBaseName);
        for (var suffix = 2; Directory.Exists(archiveRoot); suffix++)
        {
            archiveRoot = Path.Combine(deletedRoot, $"{archiveBaseName}_{suffix}");
        }

        Directory.CreateDirectory(archiveRoot);

        foreach (var source in sources)
        {
            var relative = Path.GetRelativePath(root, source);
            var destination = Path.Combine(archiveRoot, relative);
            var parent = Path.GetDirectoryName(destination);
            if (!string.IsNullOrWhiteSpace(parent))
            {
                Directory.CreateDirectory(parent);
            }

            Directory.Move(source, destination);
        }

        return archiveRoot;
    }

    private static void EnsureInsideOptionRoot(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        if (relative.StartsWith("..", StringComparison.Ordinal) || Path.IsPathRooted(relative))
        {
            throw new InvalidOperationException($"目录不在 option 根目录内：{path}");
        }
    }

    private static string SafeFileName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var cleaned = new string(value
            .Select(character => invalid.Contains(character) ? '_' : character)
            .ToArray())
            .Trim();

        if (string.IsNullOrWhiteSpace(cleaned))
        {
            return "item";
        }

        return cleaned.Length <= 40 ? cleaned : cleaned[..40];
    }

    private static string BoolText(bool value)
    {
        return value ? "true" : "false";
    }

    private static void EnsureBackup(string path)
    {
        // 约定：任何文件第一次保存时复制一份 <file>.bak，且只复制一次。
        var backupPath = path + ".bak";
        if (!File.Exists(backupPath))
        {
            File.Copy(path, backupPath);
        }
    }

    private static bool IsSamePackage(string root, string pathA, string pathB)
    {
        return PackageName(root, pathA).Equals(PackageName(root, pathB), StringComparison.OrdinalIgnoreCase);
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch
        {
            // 回滚清理是尽力而为，失败不应掩盖原始异常。
        }
    }

    private static string NormalizeDifficulty(string difficulty)
    {
        var value = difficulty.Trim();
        if (value.Equals("WorldsEnd", StringComparison.OrdinalIgnoreCase))
        {
            return "WORLD'S END";
        }

        return value.ToUpperInvariant() switch
        {
            "ID_00" => "BASIC",
            "ID_01" => "ADVANCED",
            "ID_02" => "EXPERT",
            "ID_03" => "MASTER",
            "ID_04" => "ULTIMA",
            "ID_05" => "WORLD'S END",
            "ULTRA" => "ULTIMA",
            _ => value.ToUpperInvariant()
        };
    }

    private static string ResolveTemplateCharaPath(string charaRoot)
    {
        var preferred = Path.Combine(charaRoot, "chara114514", "Chara.xml");
        if (File.Exists(preferred))
        {
            return preferred;
        }

        return Directory.EnumerateFiles(charaRoot, "Chara.xml", SearchOption.AllDirectories)
            .OrderBy(path => path)
            .FirstOrDefault() ?? throw new FileNotFoundException("AZUR 下没有可用的 Chara.xml 模板。");
    }

    private static string ResolveTemplateDdsPath(string ddsRoot)
    {
        var preferred = Path.Combine(ddsRoot, "ddsImage114514", "DDSImage.xml");
        if (File.Exists(preferred))
        {
            return preferred;
        }

        return Directory.EnumerateFiles(ddsRoot, "DDSImage.xml", SearchOption.AllDirectories)
            .OrderBy(path => path)
            .FirstOrDefault() ?? throw new FileNotFoundException("AZUR 下没有可用的 DDSImage.xml 模板。");
    }

    private static HashSet<int> CollectCharacterIds(string root)
    {
        // 收集整个 option 根（含其它包与 _deleted）里所有角色的 name/id，
        // 既用于自动分配新 id，也用于显式 id 的撞号校验。
        var ids = new HashSet<int>();
        foreach (var path in Directory.EnumerateFiles(root, "Chara.xml", SearchOption.AllDirectories))
        {
            try
            {
                var id = Int(XDocument.Load(path).Root?.Element("name"), "id");
                if (id > 0)
                {
                    ids.Add(id);
                }
            }
            catch
            {
                // 坏 XML 跳过，不影响 id 分配。
            }
        }

        return ids;
    }

    private static int NextCustomCharacterId(string root, string charaRoot)
    {
        // 只看 AZUR/chara 会和别的包里的自定义角色撞 id，也会重用刚软删除、之后可能恢复的 id，故扫描整个根。
        var maxId = CollectCharacterIds(root).DefaultIfEmpty(114513).Max();
        var nextId = Math.Max(maxId + 1, 114514);
        while (Directory.Exists(Path.Combine(charaRoot, $"chara{nextId}")))
        {
            nextId++;
        }

        return nextId;
    }

    private static int ValidateExplicitCharacterId(string root, string charaRoot, int id)
    {
        if (id <= 0)
        {
            throw new InvalidOperationException("角色 ID 必须是正整数。");
        }

        if (Directory.Exists(Path.Combine(charaRoot, $"chara{id}")))
        {
            throw new InvalidOperationException($"AZUR 下已存在 chara{id} 目录，请换一个 ID。");
        }

        if (CollectCharacterIds(root).Contains(id))
        {
            throw new InvalidOperationException($"角色 ID {id} 已被占用（option 内或 _deleted 中已存在），请换一个。");
        }

        return id;
    }

    private static string ResolveTemplateWorksPath(string root, string worksRoot)
    {
        // 优先用目标包自己的模板。
        if (Directory.Exists(worksRoot))
        {
            var local = Directory.EnumerateFiles(worksRoot, "CharaWorks.xml", SearchOption.AllDirectories)
                .OrderBy(path => path)
                .FirstOrDefault();
            if (local is not null)
            {
                return local;
            }
        }

        // 回退到 AZUR 的乳蛙作品模板，再回退到 option 内任意 CharaWorks.xml。
        var azur = Path.Combine(root, DefaultCustomCharacterPackage, "charaWorks", $"charaWorks{DefaultAzurWorksId:D6}", "CharaWorks.xml");
        if (File.Exists(azur))
        {
            return azur;
        }

        return Directory.EnumerateFiles(root, "CharaWorks.xml", SearchOption.AllDirectories)
            .Where(path => !IsDeletedPath(root, path))
            .OrderBy(path => path)
            .FirstOrDefault() ?? throw new FileNotFoundException("option 内没有可用的 CharaWorks.xml 模板。");
    }

    private static bool EnsureWorksPriority(string worksRoot, int id)
    {
        var worksPath = Directory.EnumerateFiles(worksRoot, "CharaWorks.xml", SearchOption.AllDirectories)
            .FirstOrDefault(path =>
            {
                try
                {
                    var document = XDocument.Load(path);
                    return Int(document.Root?.Element("name"), "id") == id;
                }
                catch
                {
                    return false;
                }
            });

        if (worksPath is null)
        {
            return false;
        }

        var document = XDocument.Load(worksPath);
        if (document.Root is not null)
        {
            SetText(document.Root, "priority", DefaultCustomCharacterPriority.ToString());
            SaveXml(document, worksPath);
        }

        return true;
    }

    private static void AddWorksToSortFirst(string worksSortPath, int id)
    {
        XDocument document;
        if (File.Exists(worksSortPath))
        {
            document = XDocument.Load(worksSortPath);
        }
        else
        {
            // 包内还没有 WorksSort.xml 时新建一个（带 game 期望的 xsd/xsi 命名空间声明）。
            document = new XDocument(new XElement("SerializeSortData",
                new XAttribute(XNamespace.Xmlns + "xsd", "http://www.w3.org/2001/XMLSchema"),
                new XAttribute(XNamespace.Xmlns + "xsi", "http://www.w3.org/2001/XMLSchema-instance"),
                new XElement("dataName", "charaWorks"),
                new XElement("SortList")));
            var directory = Path.GetDirectoryName(worksSortPath);
            if (!string.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }
        }

        var sortList = document.Root?.Element("SortList");
        if (sortList is null)
        {
            sortList = new XElement("SortList");
            document.Root!.Add(sortList);
        }

        foreach (var duplicate in sortList.Elements("StringID")
                     .Where(item => Int(item, "id") == id)
                     .ToList())
        {
            duplicate.Remove();
        }

        sortList.AddFirst(new XElement("StringID",
            new XElement("id", id),
            new XElement("str"),
            new XElement("data")));
        SaveXml(document, worksSortPath);
    }

    private static void RemoveWorksFromSort(string worksSortPath, int id)
    {
        if (!File.Exists(worksSortPath))
        {
            return;
        }

        var document = XDocument.Load(worksSortPath);
        var sortList = document.Root?.Element("SortList");
        if (sortList is null)
        {
            return;
        }

        var removed = sortList.Elements("StringID")
            .Where(item => Int(item, "id") == id)
            .ToList();

        if (removed.Count == 0)
        {
            return;
        }

        foreach (var duplicate in removed)
        {
            duplicate.Remove();
        }

        SaveXml(document, worksSortPath);
    }

    private static void SetText(XElement root, params string[] pathAndValue)
    {
        if (pathAndValue.Length < 2)
        {
            throw new ArgumentException("SetText requires at least one element name and a value.");
        }

        var value = pathAndValue[^1];
        var current = root;
        foreach (var name in pathAndValue.Take(pathAndValue.Length - 1))
        {
            var child = current.Element(name);
            if (child is null)
            {
                child = new XElement(name);
                current.Add(child);
            }

            current = child;
        }

        current.Value = value;
    }

    private static void SaveXml(XDocument document, string path)
    {
        var settings = new XmlWriterSettings
        {
            Encoding = new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
            Indent = true,
            NewLineChars = "\r\n"
        };

        using var writer = XmlWriter.Create(path, settings);
        document.Save(writer);
    }

    private sealed record DdsImageInfo(string Package, string XmlPath, string RelativePath, string BigPath, string SmallPath, string ThumbPath);
}

public sealed class AddCharacterRequest
{
    // 显式角色 ID（最终 ID = 基 ID × 10 + 皮肤 ID）；<=0 表示交给程序自动分配下一个空闲 id（≥114514）。
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public string SortName { get; set; } = "";
    public string IllustratorName { get; set; } = "";
    public int WorksId { get; set; } = OptionRepository.DefaultAzurWorksId;
    public string WorksName { get; set; } = "アズールレーン";
    public string SourceImagePath { get; set; } = "";
    public Dictionary<CharacterImageKind, CropSettings> Crops { get; set; } = [];
}
