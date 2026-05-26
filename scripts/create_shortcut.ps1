# Creates a Desktop shortcut "Prompt Optimizer" that launches the desktop app
# (pythonw -> no console window) with the skull icon.
#
# Run:  powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1

$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $proj ".venv\Scripts\Prompt Optimizer.exe"
$pythonw = Join-Path $proj ".venv\Scripts\pythonw.exe"
$python = Join-Path $proj ".venv\Scripts\python.exe"
$entry = Join-Path $proj "desktop.py"
$icon = Join-Path $proj "assets\skull.ico"
$appId = "Hermes.PromptOptimizer"
$appName = "Prompt Optimizer"

if (-not (Test-Path $pythonw)) {
    if (Test-Path $python) { $pythonw = $python }
    else { throw "Python not found in .venv. Run scripts\start_supervised.ps1 setup first." }
}
if (-not (Test-Path $icon)) {
    throw "Icon missing. Run: .\.venv\Scripts\python.exe scripts\make_icon.py"
}

if (-not (Test-Path $launcher)) {
    $buildLauncher = Join-Path $PSScriptRoot "build_windows_launcher.ps1"
    if (Test-Path $buildLauncher) {
        try {
            & $buildLauncher
        }
        catch {
            Write-Warning "Could not build the custom launcher; falling back to pythonw.exe. $($_.Exception.Message)"
        }
    }
}

$target = if (Test-Path $launcher) { $launcher } else { $pythonw }

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "$appName.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath = $target
$sc.Arguments = "`"$entry`""
$sc.WorkingDirectory = $proj
$sc.IconLocation = "$icon,0"
$sc.Description = $appName
$sc.WindowStyle = 1
$sc.Save()
[void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($sc)
[void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)

# Windows taskbar icons are tied to an AppUserModelID. Without this metadata,
# a pythonw.exe app can still show the default Python icon even when the .lnk
# itself has the correct custom icon.
$shortcutPropertiesType = "PromptOptimizerShortcut.ShortcutProperties" -as [type]
if (-not $shortcutPropertiesType) {
    Add-Type -Language CSharp -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace PromptOptimizerShortcut
{
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    internal class CShellLink { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    internal interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cchMaxPath, IntPtr pfd, uint fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cchMaxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cchMaxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cchMaxPath);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cchIconPath, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
        void Resolve(IntPtr hwnd, uint fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("0000010b-0000-0000-C000-000000000046")]
    internal interface IPersistFile
    {
        void GetClassID(out Guid pClassID);
        void IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    public interface IPropertyStore
    {
        void GetCount(out uint cProps);
        void GetAt(uint iProp, out PROPERTYKEY pkey);
        void GetValue(ref PROPERTYKEY key, out PropVariant pv);
        void SetValue(ref PROPERTYKEY key, ref PropVariant pv);
        void Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PROPERTYKEY
    {
        public Guid fmtid;
        public uint pid;

        public PROPERTYKEY(Guid fmtid, uint pid)
        {
            this.fmtid = fmtid;
            this.pid = pid;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PropVariant : IDisposable
    {
        public ushort vt;
        public ushort wReserved1;
        public ushort wReserved2;
        public ushort wReserved3;
        public IntPtr p;
        public int p2;

        public static PropVariant FromString(string value)
        {
            var pv = new PropVariant();
            pv.vt = 31; // VT_LPWSTR
            pv.p = Marshal.StringToCoTaskMemUni(value);
            return pv;
        }

        public void Dispose()
        {
            PropVariantClear(ref this);
        }

        [DllImport("Ole32.dll")]
        private static extern int PropVariantClear(ref PropVariant pvar);
    }

    public static class ShortcutProperties
    {
        private const uint GPS_READWRITE = 0x00000002;
        private static readonly Guid AppUserModelGuid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        private static readonly PROPERTYKEY RelaunchCommand = new PROPERTYKEY(AppUserModelGuid, 2);
        private static readonly PROPERTYKEY RelaunchIcon = new PROPERTYKEY(AppUserModelGuid, 3);
        private static readonly PROPERTYKEY RelaunchDisplayName = new PROPERTYKEY(AppUserModelGuid, 4);
        private static readonly PROPERTYKEY AppUserModelID = new PROPERTYKEY(AppUserModelGuid, 5);

        public static void Apply(string shortcutPath, string appId, string relaunchCommand, string displayName, string relaunchIcon)
        {
            object shellLink = new CShellLink();
            ((IPersistFile)shellLink).Load(shortcutPath, 2);
            var store = (IPropertyStore)shellLink;

            SetString(store, AppUserModelID, appId);
            SetString(store, RelaunchCommand, relaunchCommand);
            SetString(store, RelaunchDisplayName, displayName);
            SetString(store, RelaunchIcon, relaunchIcon);

            store.Commit();
            ((IPersistFile)shellLink).Save(shortcutPath, true);
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHGetPropertyStoreFromParsingName(
            [MarshalAs(UnmanagedType.LPWStr)] string pszPath,
            IntPtr pbc,
            uint flags,
            ref Guid riid,
            [MarshalAs(UnmanagedType.Interface)]
            out IPropertyStore ppv);

        private static void SetString(IPropertyStore store, PROPERTYKEY key, string value)
        {
            var pv = PropVariant.FromString(value);
            try
            {
                store.SetValue(ref key, ref pv);
            }
            finally
            {
                pv.Dispose();
            }
        }
    }
}
"@
}

$relaunchCommand = "`"$target`" `"$entry`""
$relaunchIcon = "$icon,0"
[PromptOptimizerShortcut.ShortcutProperties]::Apply($lnkPath, $appId, $relaunchCommand, $appName, $relaunchIcon)

Write-Host "Created shortcut: $lnkPath" -ForegroundColor Green
Write-Host "Target : $target `"$entry`""
Write-Host "Icon   : $icon"
Write-Host "App ID : $appId"
