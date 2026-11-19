using System.Diagnostics;
using System.Text.Json;
namespace SekiroCharacterToolkit;

static class LocalStorage
{
 public static string Home { get; private set; } = AppContext.BaseDirectory;
 public static string Data { get; private set; } = AppContext.BaseDirectory;
 public static string Config { get; private set; } = "";
 public static string Cache { get; private set; } = "";
 public static void Initialize()
 {
  Home=Environment.GetEnvironmentVariable("SCT_HOME")??AppContext.BaseDirectory;
  Data=Environment.GetEnvironmentVariable("SCT_DATA_ROOT")??Home;
  Config=Environment.GetEnvironmentVariable("SCT_CONFIG")??Path.Combine(Data,"settings.json");
  string cache=Path.Combine(Data,"cache");
  if(File.Exists(Config))try{var s=JsonSerializer.Deserialize<Dictionary<string,string>>(File.ReadAllText(Config));cache=s?.GetValueOrDefault("cache",cache)??cache;}catch(JsonException){}
  if(!Path.IsPathRooted(cache))cache=Path.GetFullPath(cache,Data);
  ApplyCurrent(cache);
 }
 public static Dictionary<string,string> Variables(string cache)
 {
  cache=Path.GetFullPath(cache);
  var map=new Dictionary<string,string>();
  foreach(var pair in new Dictionary<string,string>{
   ["TEMP"]="temp",["TMP"]="temp",["TMPDIR"]="temp",["APPDATA"]="profile/AppData/Roaming",
   ["LOCALAPPDATA"]="profile/AppData/Local",["USERPROFILE"]="profile",["HOME"]="profile",
   ["XDG_CACHE_HOME"]="xdg/cache",["XDG_CONFIG_HOME"]="xdg/config",["XDG_DATA_HOME"]="xdg/data",
   ["BLENDER_USER_CONFIG"]="blender/config",["BLENDER_USER_SCRIPTS"]="blender/scripts",
   ["BLENDER_USER_DATAFILES"]="blender/datafiles",["BLENDER_USER_EXTENSIONS"]="blender/extensions",
   ["DOTNET_CLI_HOME"]="dotnet",["DOTNET_BUNDLE_EXTRACT_BASE_DIR"]="dotnet/bundles",
   ["NUGET_PACKAGES"]="nuget",["PIP_CACHE_DIR"]="pip",["PYTHONUSERBASE"]="python",
   ["MPLCONFIGDIR"]="matplotlib",["NUMBA_CACHE_DIR"]="numba",["CUDA_CACHE_PATH"]="cuda",["OPTIX_CACHE_PATH"]="optix"})
  {var p=Path.GetFullPath(Path.Combine(cache,pair.Value));Directory.CreateDirectory(p);map[pair.Key]=p;}
  map["SCT_CACHE_ROOT"]=cache;map["SCT_AUDIO_CACHE"]=cache;map["PYTHONNOUSERSITE"]="1";
  map["PYTHONDONTWRITEBYTECODE"]="1";map["PYTHONIOENCODING"]="utf-8";map["DOTNET_CLI_TELEMETRY_OPTOUT"]="1";
  return map;
 }
 public static void ApplyCurrent(string cache)
 {
  Cache=Path.GetFullPath(cache);foreach(var kv in Variables(Cache))Environment.SetEnvironmentVariable(kv.Key,kv.Value);
  Environment.CurrentDirectory=Cache;
 }
 public static void Apply(ProcessStartInfo info,string cache)
 {
  foreach(var kv in Variables(cache))info.Environment[kv.Key]=kv.Value;
  info.WorkingDirectory=Path.GetFullPath(cache);
 }
}
