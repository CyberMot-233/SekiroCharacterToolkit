using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
namespace SekiroCharacterToolkit;
class Program { [STAThread] public static void Main(string[] args){LocalStorage.Initialize();AppBuilder.Configure<App>().UsePlatformDetect().LogToTrace().StartWithClassicDesktopLifetime(args);} }
public partial class App:Application {public override void Initialize()=>AvaloniaXamlLoader.Load(this);public override void OnFrameworkInitializationCompleted(){if(ApplicationLifetime is IClassicDesktopStyleApplicationLifetime d)d.MainWindow=new MainWindow(d.Args??[]);base.OnFrameworkInitializationCompleted();}}
