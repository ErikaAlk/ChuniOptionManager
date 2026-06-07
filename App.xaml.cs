using Microsoft.UI.Xaml;
using System.Text;

namespace ChuniOptionManager;

public partial class App : Application
{
    private Window? _window;

    public App()
    {
        UnhandledException += App_UnhandledException;
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
        TaskScheduler.UnobservedTaskException += TaskScheduler_UnobservedTaskException;

        try
        {
            InitializeComponent();
        }
        catch (Exception ex)
        {
            LogCrash("App.InitializeComponent", ex);
            throw;
        }
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            _window = new MainWindow();
            _window.Activate();
        }
        catch (Exception ex)
        {
            LogCrash("App.OnLaunched", ex);
            throw;
        }
    }

    internal static void LogCrash(string scope, Exception ex)
    {
        try
        {
            var builder = new StringBuilder()
                .AppendLine($"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {scope}")
                .AppendLine(ex.ToString())
                .AppendLine();

            File.AppendAllText(Path.Combine(AppContext.BaseDirectory, "startup.log"), builder.ToString());
        }
        catch
        {
            // Last-resort logging must never create another startup failure.
        }
    }

    private void App_UnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        LogCrash("Application.UnhandledException", e.Exception);
    }

    private static void CurrentDomain_UnhandledException(object sender, System.UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
        {
            LogCrash("AppDomain.UnhandledException", ex);
        }
    }

    private static void TaskScheduler_UnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        LogCrash("TaskScheduler.UnobservedTaskException", e.Exception);
    }
}
