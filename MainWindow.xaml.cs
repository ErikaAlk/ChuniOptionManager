using System.Collections.ObjectModel;
using System.Diagnostics;
using ChuniOptionManager.Models;
using ChuniOptionManager.Services;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace ChuniOptionManager;

public sealed partial class MainWindow : Window
{
    private OptionCatalog _catalog = new();
    private MusicItem? _selectedSong;
    private CharacterItem? _selectedCharacter;
    private string _currentRoot = "";
    private bool _isUiReady;
    private int _statusVersion;

    public ObservableCollection<MusicItem> FilteredSongs { get; } = [];
    public ObservableCollection<CharacterItem> FilteredCharacters { get; } = [];
    public ObservableCollection<IssueItem> Issues { get; } = [];

    public MainWindow()
    {
        try
        {
            InitializeComponent();
            _isUiReady = true;
            Title = "CHUNITHM Option Manager";
            ApplyDarkTitleBar(this);
            TryEnableMica();
            RootNav.SelectedItem = MusicNav;

            _currentRoot = OptionRootLocator.FindDefaultRoot();
            OptionRootBox.Text = _currentRoot;
            _ = LoadCatalogAsync();
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.ctor", ex);
            throw;
        }
    }

    private async Task LoadCatalogAsync()
    {
        if (!Directory.Exists(_currentRoot))
        {
            ShowStatus("目录不存在", _currentRoot, InfoBarSeverity.Error);
            return;
        }

        ToggleLoading(true);
        try
        {
            var root = _currentRoot;
            var catalog = await Task.Run(() => OptionRepository.Scan(root));
            _catalog = catalog;
            ApplyFilters();
            Issues.Clear();
            foreach (var issue in _catalog.Issues)
            {
                Issues.Add(issue);
            }

            IssueCountText.Text = $"排查项 {Issues.Count} 个";
            ShowStatus("扫描完成", $"歌曲 {_catalog.Songs.Count} 首，角色 {_catalog.Characters.Count} 个，排查项 {_catalog.Issues.Count} 个。", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus("扫描失败", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            ToggleLoading(false);
        }
    }

    private void ApplyFilters()
    {
        if (!_isUiReady)
        {
            return;
        }

        var query = SearchBox.Text.Trim();
        var difficulty = (DifficultyFilter.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "全部";
        var songSort = (SongSortBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "SortName";
        var characterSort = (CharacterSortBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "SortName";

        var songs = _catalog.Songs.Where(song => song.Matches(query));
        if (difficulty == "文件缺失")
        {
            songs = songs.Where(song => song.HasMissingEnabledFile);
        }
        else if (difficulty != "全部")
        {
            songs = songs.Where(song => song.HasEnabled(difficulty));
        }

        FilteredSongs.Clear();
        foreach (var song in SortSongs(songs, songSort).Take(2000))
        {
            FilteredSongs.Add(song);
        }

        var characters = _catalog.Characters.Where(character => character.Matches(query));
        FilteredCharacters.Clear();
        foreach (var character in SortCharacters(characters, characterSort).Take(2000))
        {
            FilteredCharacters.Add(character);
        }

        SongCountText.Text = $"歌曲 {FilteredSongs.Count} / {_catalog.Songs.Count} 首";
        CharacterCountText.Text = $"角色 {FilteredCharacters.Count} / {_catalog.Characters.Count} 个";
    }

    private static IEnumerable<MusicItem> SortSongs(IEnumerable<MusicItem> songs, string sort)
    {
        return sort switch
        {
            "Id" => songs.OrderBy(song => song.Id).ThenBy(song => song.SortTitle, StringComparer.CurrentCultureIgnoreCase),
            "Title" => songs.OrderBy(song => song.Title, StringComparer.CurrentCultureIgnoreCase).ThenBy(song => song.Id),
            "Package" => songs.OrderBy(song => song.Package, StringComparer.OrdinalIgnoreCase).ThenBy(song => song.SortTitle, StringComparer.CurrentCultureIgnoreCase),
            "Difficulty" => songs
                .OrderByDescending(song => song.PrimaryChart is null ? -1 : DifficultyPalette.Rank(song.PrimaryChart.Difficulty))
                .ThenByDescending(song => song.PrimaryChart?.Level ?? -1)
                .ThenBy(song => song.SortTitle, StringComparer.CurrentCultureIgnoreCase),
            "Missing" => songs
                .OrderByDescending(song => song.HasMissingEnabledFile)
                .ThenBy(song => song.SortTitle, StringComparer.CurrentCultureIgnoreCase),
            _ => songs.OrderBy(song => song.SortTitle, StringComparer.CurrentCultureIgnoreCase).ThenBy(song => song.Id)
        };
    }

    private static IEnumerable<CharacterItem> SortCharacters(IEnumerable<CharacterItem> characters, string sort)
    {
        return sort switch
        {
            "Id" => characters.OrderBy(character => character.Id).ThenBy(character => character.SortName, StringComparer.CurrentCultureIgnoreCase),
            "Name" => characters.OrderBy(character => character.Name, StringComparer.CurrentCultureIgnoreCase).ThenBy(character => character.Id),
            "Works" => characters.OrderBy(character => character.Works, StringComparer.CurrentCultureIgnoreCase).ThenBy(character => character.SortName, StringComparer.CurrentCultureIgnoreCase),
            "Priority" => characters.OrderByDescending(character => character.Priority).ThenBy(character => character.SortName, StringComparer.CurrentCultureIgnoreCase),
            "Package" => characters.OrderBy(character => character.Package, StringComparer.OrdinalIgnoreCase).ThenBy(character => character.SortName, StringComparer.CurrentCultureIgnoreCase),
            _ => characters.OrderBy(character => character.SortName, StringComparer.CurrentCultureIgnoreCase).ThenBy(character => character.Id)
        };
    }

    private async void PickFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.FileTypeFilter.Add("*");
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
        {
            return;
        }

        if (!OptionRootLocator.LooksLikeOptionRoot(folder.Path))
        {
            ShowStatus("目录不像 option 根目录", "请选择包含 A001/A300/AXVX 等 option 包的文件夹。", InfoBarSeverity.Warning);
            return;
        }

        _currentRoot = folder.Path;
        OptionRootBox.Text = _currentRoot;
        await LoadCatalogAsync();
    }

    private async void Reload_Click(object sender, RoutedEventArgs e)
    {
        await LoadCatalogAsync();
    }

    private async void AddCharacter_Click(object sender, RoutedEventArgs e)
    {
        var selectedImagePath = "";
        var crops = new Dictionary<CharacterImageKind, CropSettings>
        {
            [CharacterImageKind.Big] = new() { Zoom = 1.0, OffsetX = 0, OffsetY = 0 },
            [CharacterImageKind.Small] = new() { Zoom = 1.45, OffsetX = 0, OffsetY = -28 },
            [CharacterImageKind.Thumb] = new() { Zoom = 3.0, OffsetX = 0, OffsetY = -62 }
        };
        var baseIdBox = new TextBox { PlaceholderText = "角色基ID（例如 2469）" };
        var skinIdBox = new TextBox { Text = "0" };
        var finalIdBox = new TextBox { IsReadOnly = true, PlaceholderText = "基 ID 留空＝自动分配（≥114514）" };

        // 最终 ID = 基 ID × 10 + 皮肤 ID；基 ID 留空表示自动分配。实时回填到只读的「最终 ID」框。
        void UpdateFinalId()
        {
            if (string.IsNullOrWhiteSpace(baseIdBox.Text))
            {
                finalIdBox.Text = "";
                return;
            }

            finalIdBox.Text = TryComposeCharacterId(baseIdBox.Text, skinIdBox.Text, out var composed)
                ? composed.ToString()
                : "无效";
        }

        baseIdBox.TextChanged += (_, _) => UpdateFinalId();
        skinIdBox.TextChanged += (_, _) => UpdateFinalId();
        UpdateFinalId();

        var nameBox = new TextBox { PlaceholderText = "角色显示名" };
        var illustratorBox = new TextBox { PlaceholderText = "绘师 / illustratorName.str（可选，不填则 Invalid）" };
        var worksBox = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
        PopulateWorksBox(worksBox, OptionRepository.DefaultAzurWorksId);

        var bigPathBox = CreateReadOnlyPathBox("由「单图快速生成」填充");
        var smallPathBox = CreateReadOnlyPathBox("由「单图快速生成」填充");
        var thumbPathBox = CreateReadOnlyPathBox("由「单图快速生成」填充");
        var bigRow = CreateTextureFileRow(bigPathBox, "参考分辨率：1024 x 1024 像素。");
        var smallRow = CreateTextureFileRow(smallPathBox, "参考分辨率：512 x 512 像素。");
        var thumbRow = CreateTextureFileRow(thumbPathBox, "参考分辨率：128 x 128 像素。");
        bigRow.Visibility = Visibility.Collapsed;
        smallRow.Visibility = Visibility.Collapsed;
        thumbRow.Visibility = Visibility.Collapsed;

        async Task OpenQuickCropAsync()
        {
            var result = await ShowQuickCropWindowAsync(crops, selectedImagePath);
            if (result is null)
            {
                return;
            }

            selectedImagePath = result;
            if (string.IsNullOrWhiteSpace(result))
            {
                bigPathBox.Text = "";
                smallPathBox.Text = "";
                thumbPathBox.Text = "";
                bigRow.Visibility = Visibility.Collapsed;
                smallRow.Visibility = Visibility.Collapsed;
                thumbRow.Visibility = Visibility.Collapsed;
                return;
            }

            var fileName = Path.GetFileName(result);
            bigPathBox.Text = $"单图裁剪：{fileName} -> big.dds";
            smallPathBox.Text = $"单图裁剪：{fileName} -> small.dds";
            thumbPathBox.Text = $"单图裁剪：{fileName} -> thumb.dds";
            bigRow.Visibility = Visibility.Visible;
            smallRow.Visibility = Visibility.Visible;
            thumbRow.Visibility = Visibility.Visible;
        }

        var quickButton = new Button { Content = "单图快速生成三张贴图..." };
        quickButton.Click += async (_, _) => await OpenQuickCropAsync();

        var dialogContent = new StackPanel { Width = 760, Spacing = 18 };
        dialogContent.Children.Add(CreateIdentityPanel(baseIdBox, skinIdBox, finalIdBox, nameBox, illustratorBox, worksBox));
        dialogContent.Children.Add(CreateTexturePanel(quickButton, bigRow, smallRow, thumbRow));
        dialogContent.Children.Add(new TextBlock
        {
            Text = "提示：角色名请尽量使用日语字库内可显示字符；超出字库的汉字在游戏内可能显示为方块。",
            FontSize = 17,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 255, 119, 0))
        });

        var dialog = new ContentDialog
        {
            Title = "新增角色",
            Content = new ScrollViewer
            {
                Content = dialogContent,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                MaxHeight = 820
            },
            PrimaryButtonText = "生成并写入 AZUR",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = RootNav.XamlRoot
        };

        // ContentDialog 的实际宽度受主题资源 ContentDialogMaxWidth（默认 548）限制，
        // 不抬高这个值，再大的 Width 也会被裁切、看起来还偏。
        dialog.Resources["ContentDialogMaxWidth"] = 880.0;
        dialog.Resources["ContentDialogMinWidth"] = 820.0;

        var result = await dialog.ShowAsync();
        if (result != ContentDialogResult.Primary)
        {
            return;
        }

        var selectedWorks = (worksBox.SelectedItem as ComboBoxItem)?.Tag as Models.WorksItem;

        // 解析显式 ID：基 ID 留空＝自动分配（0）；填了就必须能组成有效 ID，否则拦下不提交。
        var requestedId = 0;
        if (!string.IsNullOrWhiteSpace(baseIdBox.Text)
            && !TryComposeCharacterId(baseIdBox.Text, skinIdBox.Text, out requestedId))
        {
            ShowStatus("ID 无效", "基 ID 需为正整数、皮肤 ID 需为 0–9；或清空基 ID 以自动分配。", InfoBarSeverity.Error);
            return;
        }

        try
        {
            var newId = OptionRepository.AddCharacter(_currentRoot, new AddCharacterRequest
            {
                Id = requestedId,
                Name = nameBox.Text,
                SortName = nameBox.Text,
                IllustratorName = illustratorBox.Text,
                WorksId = selectedWorks?.Id ?? 0,
                WorksName = selectedWorks?.Name ?? "",
                SourceImagePath = selectedImagePath,
                Crops = crops.ToDictionary(
                    item => item.Key,
                    item => new CropSettings
                    {
                        Zoom = item.Value.Zoom,
                        OffsetX = item.Value.OffsetX,
                        OffsetY = item.Value.OffsetY
                    })
            });
            await LoadCatalogAsync();
            ShowStatus("已添加角色", $"{nameBox.Text.Trim()} 已写入 AZUR（ID {newId}，priority=999）。", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus("添加角色失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private static TextBox CreateReadOnlyPathBox(string placeholder)
    {
        return new TextBox
        {
            PlaceholderText = placeholder,
            IsReadOnly = true,
            HorizontalAlignment = HorizontalAlignment.Stretch
        };
    }

    // 由基 ID 与皮肤 ID 组成最终角色 ID：最终 ID = 基 ID × 10 + 皮肤 ID（皮肤为个位 0–9，0 即默认皮肤）。
    // 例：基 11451 + 皮肤 4 = 114514（模板号）；基 2469 + 皮肤 0 = 24690。
    private static bool TryComposeCharacterId(string baseText, string skinText, out int composed)
    {
        composed = 0;
        if (!int.TryParse((baseText ?? "").Trim(), out var baseId) || baseId <= 0)
        {
            return false;
        }

        var normalizedSkin = string.IsNullOrWhiteSpace(skinText) ? "0" : skinText.Trim();
        if (!int.TryParse(normalizedSkin, out var skinId) || skinId is < 0 or > 9)
        {
            return false;
        }

        composed = baseId * 10 + skinId;
        return true;
    }

    private FrameworkElement CreateIdentityPanel(
        TextBox baseIdBox,
        TextBox skinIdBox,
        TextBox finalIdBox,
        TextBox nameBox,
        TextBox illustratorBox,
        ComboBox worksBox)
    {
        var grid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = new GridLength(160) },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }
            },
            RowSpacing = 12,
            ColumnSpacing = 12
        };

        for (var index = 0; index < 8; index++)
        {
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        }

        AddFormHeader(grid, "ID 与名称", 0);
        AddFormRow(grid, "基 ID", baseIdBox, 1);
        AddFormRow(grid, "皮肤 ID", skinIdBox, 2);
        AddFormRow(grid, "最终 ID", finalIdBox, 3);

        var nameRow = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = GridLength.Auto }
            },
            ColumnSpacing = 8
        };
        nameRow.Children.Add(nameBox);
        var searchButton = new Button
        {
            Content = new SymbolIcon(Symbol.Find),
            Width = 44,
            Height = 44
        };
        Grid.SetColumn(searchButton, 1);
        nameRow.Children.Add(searchButton);
        AddFormRow(grid, "角色名", nameRow, 4);
        AddFormRow(grid, "绘师（可选）", illustratorBox, 5);

        var worksRow = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = GridLength.Auto },
                new ColumnDefinition { Width = GridLength.Auto }
            },
            ColumnSpacing = 10
        };
        worksRow.Children.Add(worksBox);
        var newWorksButton = new Button { Content = "新建...", Height = 44 };
        newWorksButton.Click += async (_, _) =>
        {
            var works = await ShowAddWorksWindowAsync();
            if (works is not null)
            {
                PopulateWorksBox(worksBox, works.Id);
                ShowStatus("已新建作品", $"{works.Display} 已写入 AZUR\\charaWorks。", InfoBarSeverity.Success);
            }
        };
        Grid.SetColumn(newWorksButton, 1);
        worksRow.Children.Add(newWorksButton);
        var manageWorksButton = new Button { Content = "管理库...", Height = 44 };
        manageWorksButton.Click += async (_, _) =>
        {
            var selectedId = ((worksBox.SelectedItem as ComboBoxItem)?.Tag as Models.WorksItem)?.Id ?? OptionRepository.DefaultAzurWorksId;
            await ShowManageWorksWindowAsync();
            PopulateWorksBox(worksBox, selectedId);
            // 删除作品会连带删角色，刷新主目录让歌曲/角色列表同步。
            await LoadCatalogAsync();
        };
        Grid.SetColumn(manageWorksButton, 2);
        worksRow.Children.Add(manageWorksButton);
        AddFormRow(grid, "作品（works）", worksRow, 6);

        var hint = new TextBlock
        {
            Text = "若不填写有效的作品（works），游戏内选角界面可能无法按作品分类检索到该角色，往往只能出现在「最近使用」等分类；长时间不用可能从列表中消失。",
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 255, 119, 0)),
            TextWrapping = TextWrapping.Wrap
        };
        Grid.SetRow(hint, 7);
        Grid.SetColumnSpan(hint, 2);
        grid.Children.Add(hint);

        return CreateDialogPanel(grid);
    }

    private FrameworkElement CreateTexturePanel(Button quickButton, params FrameworkElement[] rows)
    {
        var stack = new StackPanel { Spacing = 12 };
        stack.Children.Add(new TextBlock
        {
            Text = "贴图（CHU_UI_Character：全身_00 / 半身_01 / 大头_02）",
            FontSize = 20,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold
        });
        stack.Children.Add(quickButton);
        foreach (var row in rows)
        {
            stack.Children.Add(row);
        }

        return CreateDialogPanel(stack);
    }

    private static FrameworkElement CreateTextureFileRow(TextBox pathBox, string hint)
    {
        return new StackPanel
        {
            Spacing = 4,
            Children =
            {
                pathBox,
                new TextBlock
                {
                    Text = hint,
                    Foreground = Application.Current.Resources["SoftTextBrush"] as Brush
                }
            }
        };
    }

    private static void AddFormHeader(Grid grid, string text, int row)
    {
        var header = new TextBlock
        {
            Text = text,
            FontSize = 20,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold
        };
        Grid.SetRow(header, row);
        Grid.SetColumnSpan(header, 2);
        grid.Children.Add(header);
    }

    private static void AddFormRow(Grid grid, string label, FrameworkElement input, int row)
    {
        var labelBlock = new TextBlock
        {
            Text = label,
            FontSize = 18,
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetRow(labelBlock, row);
        grid.Children.Add(labelBlock);

        Grid.SetRow(input, row);
        Grid.SetColumn(input, 1);
        grid.Children.Add(input);
    }

    private static Border CreateDialogPanel(UIElement child)
    {
        return new Border
        {
            Padding = new Thickness(20),
            CornerRadius = new CornerRadius(8),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 38, 38, 38)),
            Child = child
        };
    }

    private async Task<string?> ShowQuickCropWindowAsync(Dictionary<CharacterImageKind, CropSettings> crops, string initialImagePath)
    {
        var resultSource = new TaskCompletionSource<string?>();
        var workingCrops = crops.ToDictionary(
            item => item.Key,
            item => new CropSettings
            {
                Zoom = item.Value.Zoom,
                OffsetX = item.Value.OffsetX,
                OffsetY = item.Value.OffsetY
            });

        var selectedPath = initialImagePath;
        var sourceWidth = 1;
        var sourceHeight = 1;
        if (!string.IsNullOrWhiteSpace(selectedPath) && File.Exists(selectedPath))
        {
            // 防御：初始图片可能在两次打开之间被删/改成 GDI+ 读不了的格式，读失败就当作未选图，别让裁剪窗崩掉。
            try
            {
                using var image = System.Drawing.Image.FromFile(selectedPath);
                sourceWidth = image.Width;
                sourceHeight = image.Height;
            }
            catch (Exception ex)
            {
                App.LogCrash("MainWindow.ShowQuickCropWindow.LoadImage", ex);
                selectedPath = "";
            }
        }

        var panes = new[]
        {
            new CharacterCropPane(CharacterImageKind.Big, "全身", "big.dds", 1080, workingCrops[CharacterImageKind.Big], 500, showFooter: false),
            new CharacterCropPane(CharacterImageKind.Small, "半身", "small.dds", 512, workingCrops[CharacterImageKind.Small], 500, showFooter: false),
            new CharacterCropPane(CharacterImageKind.Thumb, "大头", "thumb.dds", 128, workingCrops[CharacterImageKind.Thumb], 500, showFooter: false)
        };

        void UpdatePaneSources()
        {
            foreach (var pane in panes)
            {
                pane.SetSource(selectedPath, sourceWidth, sourceHeight);
            }
        }

        UpdatePaneSources();

        var cropWindow = new Window
        {
            Title = "单图快速生成角色贴图"
        };

        var root = new Grid
        {
            Padding = new Thickness(14),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 31, 31, 31)),
            RowDefinitions =
            {
                new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }
            }
        };

        var panel = new Border
        {
            Padding = new Thickness(10),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 42, 42, 42)),
            CornerRadius = new CornerRadius(8)
        };
        root.Children.Add(panel);

        var layout = new Grid
        {
            RowDefinitions =
            {
                new RowDefinition { Height = GridLength.Auto },
                new RowDefinition { Height = GridLength.Auto },
                new RowDefinition { Height = new GridLength(1, GridUnitType.Star) },
                new RowDefinition { Height = GridLength.Auto },
                new RowDefinition { Height = GridLength.Auto }
            },
            RowSpacing = 12
        };
        panel.Child = layout;

        layout.Children.Add(new TextBlock
        {
            Text = "上传一张 PNG 后可在三个格子分别拖拽移动，滚轮缩放；模板始终覆盖在最上层。",
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 166, 182, 200))
        });

        var opacityRow = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = GridLength.Auto },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }
            },
            ColumnSpacing = 12
        };
        var opacityLabel = new TextBlock
        {
            Text = "覆盖图透明度",
            FontSize = 18,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            VerticalAlignment = VerticalAlignment.Center
        };
        opacityRow.Children.Add(opacityLabel);
        var opacitySlider = new Slider
        {
            Minimum = 0.2,
            Maximum = 1,
            Value = 0.67,
            VerticalAlignment = VerticalAlignment.Center
        };
        opacitySlider.ValueChanged += (_, args) =>
        {
            foreach (var pane in panes)
            {
                pane.SetImageOpacity(args.NewValue);
            }
        };
        Grid.SetColumn(opacitySlider, 1);
        opacityRow.Children.Add(opacitySlider);
        Grid.SetRow(opacityRow, 1);
        layout.Children.Add(opacityRow);

        var paneGrid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }
            },
            ColumnSpacing = 4
        };
        for (var index = 0; index < panes.Length; index++)
        {
            Grid.SetColumn(panes[index].Root, index);
            paneGrid.Children.Add(panes[index].Root);
        }

        Grid.SetRow(paneGrid, 2);
        layout.Children.Add(paneGrid);

        var labelGrid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }
            }
        };
        foreach (var (label, column) in new[] { ("全身", 0), ("半身", 1), ("大头", 2) })
        {
            var text = new TextBlock
            {
                Text = label,
                FontSize = 18,
                FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                HorizontalAlignment = HorizontalAlignment.Center
            };
            Grid.SetColumn(text, column);
            labelGrid.Children.Add(text);
        }

        Grid.SetRow(labelGrid, 3);
        layout.Children.Add(labelGrid);

        var commandRow = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = GridLength.Auto },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = GridLength.Auto },
                new ColumnDefinition { Width = GridLength.Auto }
            },
            ColumnSpacing = 8
        };
        var uploadButton = new Button { Content = "上传 PNG 到三个格子", Height = 42 };
        uploadButton.Click += async (_, _) =>
        {
            var picked = await PickSourceImageAsync();
            if (picked is null)
            {
                return;
            }

            selectedPath = picked.Value.Path;
            sourceWidth = picked.Value.Width;
            sourceHeight = picked.Value.Height;
            UpdatePaneSources();
        };
        commandRow.Children.Add(uploadButton);

        var cancelButton = new Button { Content = "取消", Height = 42, MinWidth = 80 };
        cancelButton.Click += (_, _) =>
        {
            resultSource.TrySetResult(null);
            cropWindow.Close();
        };
        Grid.SetColumn(cancelButton, 2);
        commandRow.Children.Add(cancelButton);

        var generateButton = new Button
        {
            Content = "生成并回填",
            Height = 42,
            MinWidth = 126,
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 31, 224, 242)),
            Foreground = new SolidColorBrush(Colors.Black)
        };
        generateButton.Click += (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(selectedPath))
            {
                resultSource.TrySetResult("");
            }
            else
            {
                foreach (var item in workingCrops)
                {
                    crops[item.Key].Zoom = item.Value.Zoom;
                    crops[item.Key].OffsetX = item.Value.OffsetX;
                    crops[item.Key].OffsetY = item.Value.OffsetY;
                }

                resultSource.TrySetResult(selectedPath);
            }

            cropWindow.Close();
        };
        Grid.SetColumn(generateButton, 3);
        commandRow.Children.Add(generateButton);

        Grid.SetRow(commandRow, 4);
        layout.Children.Add(commandRow);

        cropWindow.Content = root;
        cropWindow.Closed += (_, _) => resultSource.TrySetResult(null);
        cropWindow.Activate();
        ApplyDarkTitleBar(cropWindow);
        try
        {
            var hwnd = WindowNative.GetWindowHandle(cropWindow);
            var windowId = Win32Interop.GetWindowIdFromWindow(hwnd);
            AppWindow.GetFromWindowId(windowId).Resize(new SizeInt32(1500, 820));
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.ShowQuickCropWindow.Resize", ex);
        }

        return await resultSource.Task;
    }

    private async Task<(string Path, int Width, int Height)?> PickSourceImageAsync()
    {
        var picker = new FileOpenPicker();
        picker.FileTypeFilter.Add(".png");
        picker.FileTypeFilter.Add(".jpg");
        picker.FileTypeFilter.Add(".jpeg");
        picker.FileTypeFilter.Add(".bmp");
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            return null;
        }

        // System.Drawing (GDI+) 读不了的图（WebP、损坏文件、改了扩展名的非图片）会抛异常；
        // 这里在 async void 的上传回调里，不接住就会变成未处理异常直接崩掉整个程序。
        try
        {
            using var image = System.Drawing.Image.FromFile(file.Path);
            return (file.Path, image.Width, image.Height);
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.PickSourceImage", ex);
            ShowStatus("无法读取图片", "请选择有效的 PNG / JPG / BMP 图片（不支持 WebP 等格式）。", InfoBarSeverity.Error);
            return null;
        }
    }

    private void PopulateWorksBox(ComboBox worksBox, int selectId)
    {
        worksBox.Items.Clear();
        try
        {
            foreach (var works in OptionRepository.ListWorks(_currentRoot)
                         .GroupBy(item => item.Id)
                         .Select(group => group.First()))
            {
                worksBox.Items.Add(new ComboBoxItem { Content = works.Display, Tag = works });
            }
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.PopulateWorksBox", ex);
        }

        worksBox.Items.Add(new ComboBoxItem { Content = "（不填）Invalid - 检索可能受限", Tag = null });

        var match = worksBox.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => item.Tag is Models.WorksItem works && works.Id == selectId);
        worksBox.SelectedItem = match ?? worksBox.Items.OfType<ComboBoxItem>().FirstOrDefault();
    }

    private Task<Models.WorksItem?> ShowAddWorksWindowAsync()
    {
        var resultSource = new TaskCompletionSource<Models.WorksItem?>();

        var packageBox = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
        foreach (var package in OptionRepository.ListWorksPackages(_currentRoot))
        {
            packageBox.Items.Add(new ComboBoxItem { Content = package });
        }

        packageBox.SelectedItem = packageBox.Items.OfType<ComboBoxItem>()
            .FirstOrDefault(item => (item.Content as string) == "AZUR")
            ?? packageBox.Items.OfType<ComboBoxItem>().FirstOrDefault();

        var idBox = new TextBox { PlaceholderText = "作品 ID（正整数，需唯一）" };
        var nameBox = new TextBox { PlaceholderText = "作品显示名（如 アズールレーン）" };
        var sortBox = new TextBox { PlaceholderText = "排序名（可选，留空用显示名）" };
        var errorText = new TextBlock
        {
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 255, 119, 0)),
            TextWrapping = TextWrapping.Wrap,
            Visibility = Visibility.Collapsed
        };

        var fields = new StackPanel { Spacing = 12 };
        fields.Children.Add(CreateLabeledField("写入包（文件夹）", packageBox));
        fields.Children.Add(CreateLabeledField("作品 ID", idBox));
        fields.Children.Add(CreateLabeledField("作品名", nameBox));
        fields.Children.Add(CreateLabeledField("排序名", sortBox));
        fields.Children.Add(errorText);

        var cancelButton = new Button { Content = "取消", Height = 42, MinWidth = 84 };
        var createButton = new Button
        {
            Content = "创建",
            Height = 42,
            MinWidth = 110,
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 31, 224, 242)),
            Foreground = new SolidColorBrush(Colors.Black)
        };
        var buttonRow = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 10,
            HorizontalAlignment = HorizontalAlignment.Right,
            Children = { cancelButton, createButton }
        };

        var panel = new StackPanel { Spacing = 16 };
        panel.Children.Add(new TextBlock
        {
            Text = "新建作品",
            FontSize = 20,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold
        });
        panel.Children.Add(fields);
        panel.Children.Add(buttonRow);

        var win = new Window { Title = "新建作品" };
        win.Content = new Border
        {
            Padding = new Thickness(18),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 31, 31, 31)),
            Child = panel
        };

        cancelButton.Click += (_, _) =>
        {
            resultSource.TrySetResult(null);
            win.Close();
        };
        createButton.Click += (_, _) =>
        {
            if (!int.TryParse(idBox.Text.Trim(), out var id) || id <= 0)
            {
                errorText.Text = "作品 ID 必须是正整数。";
                errorText.Visibility = Visibility.Visible;
                return;
            }

            if (string.IsNullOrWhiteSpace(nameBox.Text))
            {
                errorText.Text = "作品名不能为空。";
                errorText.Visibility = Visibility.Visible;
                return;
            }

            var package = (packageBox.SelectedItem as ComboBoxItem)?.Content as string;
            if (string.IsNullOrWhiteSpace(package))
            {
                errorText.Text = "请选择写入的包（文件夹）。";
                errorText.Visibility = Visibility.Visible;
                return;
            }

            try
            {
                var works = OptionRepository.AddWorks(_currentRoot, package, id, nameBox.Text, sortBox.Text);
                resultSource.TrySetResult(works);
                win.Close();
            }
            catch (Exception ex)
            {
                errorText.Text = ex.Message;
                errorText.Visibility = Visibility.Visible;
            }
        };

        win.Closed += (_, _) => resultSource.TrySetResult(null);
        win.Activate();
        ApplyDarkTitleBar(win);
        SizeAndCenterWindow(win, 760, 620);
        return resultSource.Task;
    }

    private Task ShowManageWorksWindowAsync()
    {
        var resultSource = new TaskCompletionSource<bool>();
        var win = new Window { Title = "作品库管理" };

        var rows = new StackPanel { Spacing = 10 };
        var emptyHint = new TextBlock
        {
            Text = "作品库为空（option 内没有自定义 CharaWorks.xml）。",
            Foreground = Application.Current.Resources["SoftTextBrush"] as Brush,
            Visibility = Visibility.Collapsed
        };

        void Reload()
        {
            rows.Children.Clear();
            List<Models.WorksItem> works;
            try
            {
                works = OptionRepository.ListWorks(_currentRoot);
            }
            catch (Exception ex)
            {
                App.LogCrash("MainWindow.ShowManageWorksWindow.Reload", ex);
                works = [];
            }

            emptyHint.Visibility = works.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            foreach (var item in works)
            {
                rows.Children.Add(BuildWorksRow(item, Reload));
            }
        }

        Reload();

        var scroll = new ScrollViewer
        {
            Content = new StackPanel { Spacing = 10, Children = { emptyHint, rows } },
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        };

        var closeButton = new Button
        {
            Content = "关闭",
            Height = 42,
            MinWidth = 96,
            HorizontalAlignment = HorizontalAlignment.Right
        };
        closeButton.Click += (_, _) => win.Close();

        var layout = new Grid
        {
            RowDefinitions =
            {
                new RowDefinition { Height = GridLength.Auto },
                new RowDefinition { Height = new GridLength(1, GridUnitType.Star) },
                new RowDefinition { Height = GridLength.Auto }
            },
            RowSpacing = 12,
            Padding = new Thickness(18)
        };
        layout.Children.Add(new TextBlock
        {
            Text = "作品库管理（编辑名称 / 删除）。删除作品会连带删除属于它的角色，需点两次确认。",
            FontSize = 18,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap
        });
        Grid.SetRow(scroll, 1);
        layout.Children.Add(scroll);
        Grid.SetRow(closeButton, 2);
        layout.Children.Add(closeButton);

        win.Content = new Border
        {
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 31, 31, 31)),
            Child = layout
        };
        win.Closed += (_, _) => resultSource.TrySetResult(true);
        win.Activate();
        ApplyDarkTitleBar(win);
        SizeAndCenterWindow(win, 900, 820);
        return resultSource.Task;
    }

    private FrameworkElement BuildWorksRow(Models.WorksItem works, Action reload)
    {
        var nameBox = new TextBox { Text = works.Name, Header = "名称" };
        var sortBox = new TextBox { Text = works.SortName, Header = "排序名" };
        var meta = new TextBlock
        {
            Text = $"ID {works.Id} · {works.Package} · priority {works.Priority}",
            Foreground = Application.Current.Resources["SoftTextBrush"] as Brush,
            FontSize = 12
        };

        var saveButton = new Button { Content = "保存" };
        saveButton.Click += (_, _) =>
        {
            works.Name = nameBox.Text.Trim();
            works.SortName = sortBox.Text.Trim();
            try
            {
                OptionRepository.UpdateWorks(works);
                meta.Text = $"ID {works.Id} · {works.Package} · priority {works.Priority} · 已保存";
            }
            catch (Exception ex)
            {
                ShowStatus("保存作品失败", ex.Message, InfoBarSeverity.Error);
            }
        };

        var deleteButton = new Button { Content = "删除" };
        var armed = false;
        deleteButton.Click += (_, _) =>
        {
            if (!armed)
            {
                armed = true;
                deleteButton.Content = "确认删除(连带角色)?";
                deleteButton.Background = new SolidColorBrush(ColorHelper.FromArgb(255, 198, 48, 48));
                deleteButton.Foreground = new SolidColorBrush(Colors.White);
                return;
            }

            try
            {
                OptionRepository.DeleteWorks(_currentRoot, works);
                reload();
            }
            catch (Exception ex)
            {
                ShowStatus("删除作品失败", ex.Message, InfoBarSeverity.Error);
            }
        };

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            VerticalAlignment = VerticalAlignment.Bottom,
            Children = { saveButton, deleteButton }
        };

        var grid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) },
                new ColumnDefinition { Width = GridLength.Auto }
            },
            ColumnSpacing = 10
        };
        grid.Children.Add(nameBox);
        Grid.SetColumn(sortBox, 1);
        grid.Children.Add(sortBox);
        Grid.SetColumn(buttons, 2);
        grid.Children.Add(buttons);

        return new Border
        {
            Padding = new Thickness(12),
            CornerRadius = new CornerRadius(8),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 42, 42, 42)),
            Child = new StackPanel { Spacing = 6, Children = { grid, meta } }
        };
    }

    private static FrameworkElement CreateLabeledField(string label, FrameworkElement input)
    {
        return new StackPanel
        {
            Spacing = 4,
            Children =
            {
                new TextBlock { Text = label, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold },
                input
            }
        };
    }

    private static void SizeAndCenterWindow(Window window, int width, int height)
    {
        try
        {
            var hwnd = WindowNative.GetWindowHandle(window);
            var windowId = Win32Interop.GetWindowIdFromWindow(hwnd);
            var appWindow = AppWindow.GetFromWindowId(windowId);
            appWindow.Resize(new SizeInt32(width, height));

            var area = DisplayArea.GetFromWindowId(windowId, DisplayAreaFallback.Nearest);
            if (area is not null)
            {
                var x = area.WorkArea.X + ((area.WorkArea.Width - width) / 2);
                var y = area.WorkArea.Y + ((area.WorkArea.Height - height) / 2);
                appWindow.Move(new PointInt32(x, y));
            }
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.SizeAndCenterWindow", ex);
        }
    }

    private void SearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_isUiReady)
        {
            ApplyFilters();
        }
    }

    private void DifficultyFilter_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isUiReady)
        {
            ApplyFilters();
        }
    }

    private void SortBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isUiReady)
        {
            ApplyFilters();
        }
    }

    private void SongGrid_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is MusicItem song)
        {
            SelectSong(song);
        }
    }

    private void SelectSong(MusicItem song)
    {
        _selectedSong = song;
        SelectedTitle.Text = song.Title;
        SelectedMeta.Text = $"ID {song.Id} · {song.Package} · {song.Genre} · {song.Artist}";
        SelectedPath.Text = song.RelativePath;
        SelectedDifficultyStrip.ItemsSource = song.EnabledCharts.ToList();
        SelectedChartsList.ItemsSource = song.Charts;
        SongEditorOverlay.Visibility = Visibility.Visible;
    }

    private void CharacterGrid_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is CharacterItem character)
        {
            SelectCharacter(character);
        }
    }

    private void SelectCharacter(CharacterItem character)
    {
        _selectedCharacter = character;
        SelectedCharacterName.Text = character.Name;
        SelectedCharacterMeta.Text = $"ID {character.Id} · {character.Package} · priority {character.Priority}";
        SelectedCharacterPath.Text = character.RelativePath;
        CharacterNameBox.Text = character.Name;
        CharacterSortNameBox.Text = character.SortName;
        CharacterWorksIdBox.Text = character.WorksId.ToString();
        CharacterWorksBox.Text = character.Works;
        CharacterPriorityBox.Text = character.Priority.ToString();
        CharacterRareTypeBox.Text = character.RareType.ToString();
        CharacterReleaseTagIdBox.Text = character.ReleaseTagId.ToString();
        CharacterReleaseTagBox.Text = character.ReleaseTag;
        CharacterNetOpenIdBox.Text = character.NetOpenId.ToString();
        CharacterNetOpenBox.Text = character.NetOpenName;
        CharacterIllustratorIdBox.Text = character.IllustratorId.ToString();
        CharacterIllustratorBox.Text = character.IllustratorName;
        CharacterExplainBox.Text = character.ExplainText;
        CharacterDisableSwitch.IsOn = character.DisableFlag;
        CharacterDefaultHaveSwitch.IsOn = character.DefaultHave;
        CharacterImageKeyText.Text = string.IsNullOrWhiteSpace(character.DdsRelativePath)
            ? $"defaultImages={character.ImageKey}\nDDSImage=未匹配"
            : $"defaultImages={character.ImageKey}\nDDSImage={character.DdsRelativePath}";

        if (CharacterImageKindBox.SelectedIndex < 0)
        {
            CharacterImageKindBox.SelectedIndex = 0;
        }

        UpdateSelectedCharacterImage();
        CharacterEditorOverlay.Visibility = Visibility.Visible;
    }

    private void CharacterImageKindBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateSelectedCharacterImage();
    }

    private void UpdateSelectedCharacterImage()
    {
        if (_selectedCharacter is null || !_isUiReady)
        {
            return;
        }

        var kind = (CharacterImageKindBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "big";
        var (source, path, label) = kind switch
        {
            "small" => (_selectedCharacter.SmallImageSource, _selectedCharacter.SmallImagePath, "small.dds"),
            "thumb" => (_selectedCharacter.ThumbImageSource, _selectedCharacter.ThumbImagePath, "thumb.dds"),
            _ => (_selectedCharacter.BigImageSource, _selectedCharacter.BigImagePath, "big.dds")
        };

        SelectedCharacterImage.Source = source;
        CharacterImageKindText.Text = label;
        SelectedCharacterImagePath.Text = string.IsNullOrWhiteSpace(path) ? "未配置图像路径" : path;
        CharacterPreviewMissingText.Visibility = source is null ? Visibility.Visible : Visibility.Collapsed;
    }

    private void RootNav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is not NavigationViewItem item)
        {
            return;
        }

        var tag = item.Tag?.ToString();
        SongEditorOverlay.Visibility = Visibility.Collapsed;
        CharacterEditorOverlay.Visibility = Visibility.Collapsed;
        MusicPage.Visibility = tag == "Music" ? Visibility.Visible : Visibility.Collapsed;
        CharactersPage.Visibility = tag == "Characters" ? Visibility.Visible : Visibility.Collapsed;
        IssuesPage.Visibility = tag == "Issues" ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void SaveSelectedSong_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedSong is null)
        {
            ShowStatus("没有选择歌曲", "先在左侧选择一首歌。", InfoBarSeverity.Warning);
            return;
        }

        try
        {
            OptionRepository.SaveChartEnableStates(_selectedSong);
            ShowStatus("已保存", $"写回 {_selectedSong.RelativePath}，首次保存会生成 .bak 备份。", InfoBarSeverity.Success);
            await LoadCatalogAsync();
            var refreshed = _catalog.Songs.FirstOrDefault(song => song.XmlPath.Equals(_selectedSong.XmlPath, StringComparison.OrdinalIgnoreCase));
            if (refreshed is not null)
            {
                SelectSong(refreshed);
            }
        }
        catch (Exception ex)
        {
            ShowStatus("保存失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private void OpenSelectedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedSong is null)
        {
            ShowStatus("没有选择歌曲", "先在左侧选择一首歌。", InfoBarSeverity.Warning);
            return;
        }

        var folder = Path.GetDirectoryName(_selectedSong.XmlPath);
        if (folder is null || !Directory.Exists(folder))
        {
            ShowStatus("目录不存在", _selectedSong.XmlPath, InfoBarSeverity.Error);
            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = folder,
            UseShellExecute = true
        });
    }

    private async void DeleteSelectedSong_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedSong is null)
        {
            ShowStatus("没有选择歌曲", "先在左侧选择一首歌。", InfoBarSeverity.Warning);
            return;
        }

        var song = _selectedSong;
        var confirmed = await ConfirmMoveToDeletedAsync(
            "删除歌曲",
            $"将把「{song.Title}」的歌曲目录移入 option\\_deleted，之后重新扫描时不会再显示。");
        if (!confirmed)
        {
            return;
        }

        try
        {
            var deletedPath = OptionRepository.DeleteMusic(_currentRoot, song);
            _selectedSong = null;
            SongEditorOverlay.Visibility = Visibility.Collapsed;
            await LoadCatalogAsync();
            ShowStatus("已删除歌曲", $"已移入 {Path.GetRelativePath(_currentRoot, deletedPath)}。", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus("删除歌曲失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void SaveSelectedCharacter_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedCharacter is null)
        {
            ShowStatus("没有选择角色", "先在角色列表里选择一个角色。", InfoBarSeverity.Warning);
            return;
        }

        if (string.IsNullOrWhiteSpace(CharacterNameBox.Text))
        {
            ShowStatus("角色保存失败", "角色名不能为空。", InfoBarSeverity.Warning);
            return;
        }

        if (!TryReadInt(CharacterWorksIdBox, "works id", out var worksId)
            || !TryReadInt(CharacterPriorityBox, "priority", out var priority)
            || !TryReadInt(CharacterRareTypeBox, "rareType", out var rareType)
            || !TryReadInt(CharacterReleaseTagIdBox, "releaseTagName id", out var releaseTagId)
            || !TryReadInt(CharacterNetOpenIdBox, "netOpenName id", out var netOpenId)
            || !TryReadInt(CharacterIllustratorIdBox, "illustratorName id", out var illustratorId))
        {
            return;
        }

        _selectedCharacter.Name = CharacterNameBox.Text.Trim();
        _selectedCharacter.SortName = string.IsNullOrWhiteSpace(CharacterSortNameBox.Text)
            ? _selectedCharacter.Name
            : CharacterSortNameBox.Text.Trim();
        _selectedCharacter.WorksId = worksId;
        _selectedCharacter.Works = CharacterWorksBox.Text.Trim();
        _selectedCharacter.Priority = priority;
        _selectedCharacter.RareType = rareType;
        _selectedCharacter.ReleaseTagId = releaseTagId;
        _selectedCharacter.ReleaseTag = CharacterReleaseTagBox.Text.Trim();
        _selectedCharacter.NetOpenId = netOpenId;
        _selectedCharacter.NetOpenName = CharacterNetOpenBox.Text.Trim();
        _selectedCharacter.IllustratorId = illustratorId;
        _selectedCharacter.IllustratorName = CharacterIllustratorBox.Text.Trim();
        _selectedCharacter.ExplainText = CharacterExplainBox.Text;
        _selectedCharacter.DisableFlag = CharacterDisableSwitch.IsOn;
        _selectedCharacter.DefaultHave = CharacterDefaultHaveSwitch.IsOn;

        try
        {
            var xmlPath = _selectedCharacter.XmlPath;
            OptionRepository.SaveCharacterSettings(_selectedCharacter);
            ShowStatus("已保存角色", $"写回 {_selectedCharacter.RelativePath}，首次保存会生成 .bak 备份。", InfoBarSeverity.Success);
            await LoadCatalogAsync();
            var refreshed = _catalog.Characters.FirstOrDefault(character => character.XmlPath.Equals(xmlPath, StringComparison.OrdinalIgnoreCase));
            if (refreshed is not null)
            {
                SelectCharacter(refreshed);
            }
        }
        catch (Exception ex)
        {
            ShowStatus("保存角色失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private void OpenSelectedCharacterFolder_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedCharacter is null)
        {
            ShowStatus("没有选择角色", "先在角色列表里选择一个角色。", InfoBarSeverity.Warning);
            return;
        }

        var folder = Path.GetDirectoryName(_selectedCharacter.XmlPath);
        if (folder is null || !Directory.Exists(folder))
        {
            ShowStatus("目录不存在", _selectedCharacter.XmlPath, InfoBarSeverity.Error);
            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = folder,
            UseShellExecute = true
        });
    }

    private async void DeleteSelectedCharacter_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedCharacter is null)
        {
            ShowStatus("没有选择角色", "先在角色列表里选择一个角色。", InfoBarSeverity.Warning);
            return;
        }

        var character = _selectedCharacter;
        var confirmed = await ConfirmMoveToDeletedAsync(
            "删除角色",
            $"将把「{character.Name}」的 Chara 目录和匹配到的 DDSImage 目录移入 option\\_deleted，之后重新扫描时不会再显示。");
        if (!confirmed)
        {
            return;
        }

        try
        {
            var deletedPath = OptionRepository.DeleteCharacter(_currentRoot, character);
            _selectedCharacter = null;
            CharacterEditorOverlay.Visibility = Visibility.Collapsed;
            await LoadCatalogAsync();
            ShowStatus("已删除角色", $"已移入 {Path.GetRelativePath(_currentRoot, deletedPath)}。", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus("删除角色失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private bool TryReadInt(TextBox textBox, string fieldName, out int value)
    {
        if (int.TryParse(textBox.Text.Trim(), out value))
        {
            return true;
        }

        ShowStatus("角色保存失败", $"{fieldName} 必须是整数。", InfoBarSeverity.Warning);
        return false;
    }

    private void ToggleLoading(bool isLoading)
    {
        SearchBox.IsEnabled = !isLoading;
        DifficultyFilter.IsEnabled = !isLoading;
        SongSortBox.IsEnabled = !isLoading;
        CharacterSortBox.IsEnabled = !isLoading;
        SongGrid.IsEnabled = !isLoading;
        CharacterGrid.IsEnabled = !isLoading;
    }

    private async Task<bool> ConfirmMoveToDeletedAsync(string title, string message)
    {
        var dialog = new ContentDialog
        {
            Title = title,
            Content = new TextBlock
            {
                Text = message,
                TextWrapping = TextWrapping.Wrap
            },
            PrimaryButtonText = "移入回收区",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = RootNav.XamlRoot
        };

        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }

    private async void ShowStatus(string title, string message, InfoBarSeverity severity)
    {
        var version = ++_statusVersion;
        StatusBar.Title = title;
        StatusBar.Message = message;
        StatusBar.Severity = severity;
        StatusBar.IsOpen = true;

        var delay = severity switch
        {
            InfoBarSeverity.Success => 4500,
            InfoBarSeverity.Warning => 6500,
            _ => 8000
        };

        await Task.Delay(delay);
        if (version == _statusVersion)
        {
            StatusBar.IsOpen = false;
        }
    }

    private sealed class CharacterCropPane
    {
        private readonly double _previewSize;
        private readonly Canvas _canvas;
        private readonly Image _image;
        private readonly TextBlock _zoomText;
        private readonly Border _zoomBadge;
        private readonly CropSettings _crop;
        private string _sourcePath = "";
        private int _sourceWidth = 1;
        private int _sourceHeight = 1;
        private bool _isDragging;
        private Windows.Foundation.Point _lastPoint;

        public CharacterCropPane(CharacterImageKind kind, string label, string fileName, int outputSize, CropSettings crop, double previewSize = 330, bool showFooter = true)
        {
            Kind = kind;
            _crop = crop;
            _previewSize = previewSize;

            _canvas = new Canvas
            {
                Width = _previewSize,
                Height = _previewSize,
                Background = new SolidColorBrush(ColorHelper.FromArgb(255, 14, 24, 38)),
                Clip = new RectangleGeometry { Rect = new Windows.Foundation.Rect(0, 0, _previewSize, _previewSize) }
            };
            _image = new Image { Stretch = Stretch.Fill };
            _zoomText = new TextBlock
            {
                Foreground = new SolidColorBrush(ColorHelper.FromArgb(210, 255, 255, 255)),
                Padding = new Thickness(7, 3, 7, 3)
            };
            _zoomBadge = new Border
            {
                Background = new SolidColorBrush(ColorHelper.FromArgb(150, 0, 0, 0)),
                CornerRadius = new CornerRadius(4),
                Margin = new Thickness(8),
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Child = _zoomText
            };

            _canvas.Children.Add(_image);
            _canvas.Children.Add(_zoomBadge);
            _canvas.PointerPressed += Canvas_PointerPressed;
            _canvas.PointerMoved += Canvas_PointerMoved;
            _canvas.PointerReleased += Canvas_PointerReleased;
            _canvas.PointerCanceled += Canvas_PointerReleased;
            _canvas.PointerWheelChanged += Canvas_PointerWheelChanged;

            var previewBorder = new Border
            {
                BorderBrush = new SolidColorBrush(ColorHelper.FromArgb(255, 45, 65, 96)),
                BorderThickness = new Thickness(1),
                Child = _canvas
            };

            Root = showFooter
                ? new StackPanel
                {
                    Spacing = 8,
                    Children =
                    {
                        previewBorder,
                        new TextBlock
                        {
                            Text = label,
                            FontSize = 16,
                            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                            HorizontalAlignment = HorizontalAlignment.Center
                        },
                        new TextBlock
                        {
                            Text = $"{fileName} · {outputSize}x{outputSize}",
                            Foreground = Application.Current.Resources["SoftTextBrush"] as Brush,
                            FontSize = 12,
                            HorizontalAlignment = HorizontalAlignment.Center
                        }
                    }
                }
                : previewBorder;

            UpdateLayout();
        }

        public CharacterImageKind Kind { get; }
        public FrameworkElement Root { get; }

        public void SetSource(string path, int width, int height)
        {
            _sourcePath = path;
            _sourceWidth = Math.Max(1, width);
            _sourceHeight = Math.Max(1, height);

            if (string.IsNullOrWhiteSpace(path))
            {
                _image.Source = null;
            }
            else
            {
                _image.Source = new BitmapImage(new Uri(path));
            }

            UpdateLayout();
        }

        public void SetImageOpacity(double opacity)
        {
            _image.Opacity = Math.Clamp(opacity, 0.2, 1.0);
        }

        private void Canvas_PointerPressed(object sender, PointerRoutedEventArgs e)
        {
            if (string.IsNullOrWhiteSpace(_sourcePath))
            {
                return;
            }

            _isDragging = true;
            _lastPoint = e.GetCurrentPoint(_canvas).Position;
            _canvas.CapturePointer(e.Pointer);
            e.Handled = true;
        }

        private void Canvas_PointerMoved(object sender, PointerRoutedEventArgs e)
        {
            if (!_isDragging || string.IsNullOrWhiteSpace(_sourcePath))
            {
                return;
            }

            var point = e.GetCurrentPoint(_canvas).Position;
            var deltaX = point.X - _lastPoint.X;
            var deltaY = point.Y - _lastPoint.Y;
            _lastPoint = point;
            MoveCrop(deltaX, deltaY);
            e.Handled = true;
        }

        private void Canvas_PointerReleased(object sender, PointerRoutedEventArgs e)
        {
            if (_isDragging)
            {
                _isDragging = false;
                _canvas.ReleasePointerCapture(e.Pointer);
                e.Handled = true;
            }
        }

        private void Canvas_PointerWheelChanged(object sender, PointerRoutedEventArgs e)
        {
            if (string.IsNullOrWhiteSpace(_sourcePath))
            {
                return;
            }

            var delta = e.GetCurrentPoint(_canvas).Properties.MouseWheelDelta;
            var factor = delta > 0 ? 1.12 : 1 / 1.12;
            _crop.Zoom = Math.Clamp(_crop.Zoom * factor, 1.0, 10.0);
            ClampOffsets();
            UpdateLayout();
            e.Handled = true;
        }

        private void MoveCrop(double deltaX, double deltaY)
        {
            var geometry = GetCropGeometry();
            var newLeft = geometry.Left - deltaX / geometry.Scale;
            var newTop = geometry.Top - deltaY / geometry.Scale;

            _crop.OffsetX = geometry.MaxX <= 0 ? 0 : Math.Clamp((newLeft / geometry.MaxX) * 200.0 - 100.0, -100.0, 100.0);
            _crop.OffsetY = geometry.MaxY <= 0 ? 0 : Math.Clamp((newTop / geometry.MaxY) * 200.0 - 100.0, -100.0, 100.0);
            UpdateLayout();
        }

        private void UpdateLayout()
        {
            _crop.Zoom = Math.Clamp(_crop.Zoom, 1.0, 10.0);
            ClampOffsets();
            _zoomText.Text = $"{_crop.Zoom:0.00}x";

            if (string.IsNullOrWhiteSpace(_sourcePath))
            {
                _image.Width = 0;
                _image.Height = 0;
                return;
            }

            var geometry = GetCropGeometry();
            _image.Width = _sourceWidth * geometry.Scale;
            _image.Height = _sourceHeight * geometry.Scale;
            Canvas.SetLeft(_image, -geometry.Left * geometry.Scale);
            Canvas.SetTop(_image, -geometry.Top * geometry.Scale);
        }

        private CropGeometry GetCropGeometry()
        {
            var cropSize = Math.Min(_sourceWidth, _sourceHeight) / Math.Clamp(_crop.Zoom, 1.0, 10.0);
            var maxX = Math.Max(0, _sourceWidth - cropSize);
            var maxY = Math.Max(0, _sourceHeight - cropSize);
            var left = maxX * ((Math.Clamp(_crop.OffsetX, -100, 100) + 100) / 200.0);
            var top = maxY * ((Math.Clamp(_crop.OffsetY, -100, 100) + 100) / 200.0);
            var scale = _previewSize / cropSize;
            return new CropGeometry(left, top, maxX, maxY, scale);
        }

        private void ClampOffsets()
        {
            _crop.OffsetX = Math.Clamp(_crop.OffsetX, -100, 100);
            _crop.OffsetY = Math.Clamp(_crop.OffsetY, -100, 100);
        }

        private readonly record struct CropGeometry(double Left, double Top, double MaxX, double MaxY, double Scale);
    }

    private void CloseEditor_Click(object sender, RoutedEventArgs e)
    {
        SongEditorOverlay.Visibility = Visibility.Collapsed;
    }

    private void SongEditorOverlay_Tapped(object sender, TappedRoutedEventArgs e)
    {
        SongEditorOverlay.Visibility = Visibility.Collapsed;
    }

    private void SongEditorPanel_Tapped(object sender, TappedRoutedEventArgs e)
    {
        e.Handled = true;
    }

    private void CloseCharacterEditor_Click(object sender, RoutedEventArgs e)
    {
        CharacterEditorOverlay.Visibility = Visibility.Collapsed;
    }

    private void CharacterEditorOverlay_Tapped(object sender, TappedRoutedEventArgs e)
    {
        CharacterEditorOverlay.Visibility = Visibility.Collapsed;
    }

    private void CharacterEditorPanel_Tapped(object sender, TappedRoutedEventArgs e)
    {
        e.Handled = true;
    }

    private static void ApplyDarkTitleBar(Window window)
    {
        try
        {
            var hwnd = WindowNative.GetWindowHandle(window);
            var windowId = Win32Interop.GetWindowIdFromWindow(hwnd);
            var appWindow = AppWindow.GetFromWindowId(windowId);

            var iconPath = Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico");
            if (File.Exists(iconPath))
            {
                appWindow.SetIcon(iconPath);
            }

            var titleBar = appWindow.TitleBar;
            var background = ColorHelper.FromArgb(255, 31, 31, 31);
            var hover = ColorHelper.FromArgb(255, 48, 48, 48);
            var pressed = ColorHelper.FromArgb(255, 64, 64, 64);
            var inactive = ColorHelper.FromArgb(255, 34, 34, 34);

            titleBar.BackgroundColor = background;
            titleBar.ForegroundColor = Colors.White;
            titleBar.InactiveBackgroundColor = inactive;
            titleBar.InactiveForegroundColor = ColorHelper.FromArgb(255, 180, 180, 180);
            titleBar.ButtonBackgroundColor = background;
            titleBar.ButtonForegroundColor = Colors.White;
            titleBar.ButtonHoverBackgroundColor = hover;
            titleBar.ButtonHoverForegroundColor = Colors.White;
            titleBar.ButtonPressedBackgroundColor = pressed;
            titleBar.ButtonPressedForegroundColor = Colors.White;
            titleBar.ButtonInactiveBackgroundColor = inactive;
            titleBar.ButtonInactiveForegroundColor = ColorHelper.FromArgb(255, 160, 160, 160);
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.ApplyDarkTitleBar", ex);
        }
    }

    private void TryEnableMica()
    {
        try
        {
            SystemBackdrop = new MicaBackdrop();
        }
        catch (Exception ex)
        {
            App.LogCrash("MainWindow.TryEnableMica", ex);
        }
    }
}
