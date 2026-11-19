# 从源码构建

普通使用请下载 [v0.10.8 单 EXE](https://github.com/Hoshino486/SekiroCharacterToolkit/releases/tag/v0.10.8)，无需编译。

## 依赖

- Windows x64；.NET SDK 9 或更新版本（项目目标为 .NET 9）。
- 已释放的 v0.10.8 工具目录，用于恢复运行组件；它可以来自首次运行发行 EXE 后选择的数据目录。
- 构建单 EXE 启动器还需要 MinGW-w64 的 gcc、g++、windres。
- CS2 编译需要另行安装 CS2 Workshop Tools，官方工具不随本项目分发。

源码仓库不提交 runtime、第三方 DLL/PYD、游戏资产、个人配置和导出结果。当前构建使用 DSAS 兼容 DLL；仅克隆仓库后执行 dotnet build 不足以恢复这些依赖。

~~~powershell
git clone https://github.com/Hoshino486/SekiroCharacterToolkit.git
cd SekiroCharacterToolkit
# 指向已释放的实际 app/版本目录；仅有一个版本时也可以指定数据目录。
./scripts/restore-runtime.ps1 -InstalledDirectory 'E:/Tools/SekiroCharacterToolkit-data/app/0.10.8-PAYLOAD_HASH'
./build.ps1
~~~

运行根目录的 SekiroCharacterToolkit.exe。GUI 与 Worker 使用自包含 .NET 发布。

## 构建单 EXE

~~~powershell
# MinGW 在包含非 ASCII 字符的临时路径上可能失败，可将本地缓存映射为闲置盘符。
New-Item -ItemType Directory -Force './cache/launcher_build'
subst Z: (Resolve-Path './cache/launcher_build').Path
try { ./src/Launcher/build.ps1 -BuildTemp 'Z:/' } finally { subst Z: /D }
./runtime/blender/4.5/python/bin/python.exe ./scripts/package_single_exe.py --root . --out ../SekiroCharacterToolkit-0.10.8-custom.exe
~~~

打包器拒绝覆盖已有输出，会逐个校验 payload 文件并输出 SHA-256。构建结果与官方 v0.10.8 的文件哈希可能不同；公开源码移除了一个未使用的开发机路径字段，打包的 v0.10.8 是此前实测的原始构建。

## 快速界面回归

~~~powershell
./SekiroCharacterToolkit.exe --e2e-navigation --test-tools --test-logs --test-report E:/Tests/sct-ui.json
~~~

自动测试会新建输出报告并退出。游戏数据、真实动画及 CS2 视觉回归需要另备输入，不能由界面测试替代。

## 组件许可

项目代码为 MIT，不改变第三方组件许可。参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [licenses](licenses)。Blender/FFmpeg 的 GPL、FMOD/Oodle 等专有运行组件以及用户提供的图标分别适用各自条款；发布二次构建时应随附相关许可与对应源码获取信息，不能将整个工具链宣称为 MIT。
