"""이 PC 의 기본 폴더 선택 창 (Windows 탐색기식 / macOS Finder / Linux zenity). LAS 변환·방 배치 화면이 쓴다."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"


# Windows: 탐색기와 같은 최신 폴더 선택 창(IFileOpenDialog). 안 되면 예전 FolderBrowserDialog 로.
_WIN_PICKER = r"""
using System;
using System.Runtime.InteropServices;
public static class LsatsFolderPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialogRCW {}
  [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint n, IntPtr spec);
    void SetFileTypeIndex(uint i);
    void GetFileTypeIndex(out uint i);
    void Advise(IntPtr sink, out uint cookie);
    void Unadvise(uint cookie);
    void SetOptions(uint fos);
    void GetOptions(out uint fos);
    void SetDefaultFolder(IShellItem si);
    void SetFolder(IShellItem si);
    void GetFolder(out IShellItem si);
    void GetCurrentSelection(out IShellItem si);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
    void GetResult(out IShellItem si);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem si);
    void GetDisplayName(uint sigdn, [MarshalAs(UnmanagedType.LPWStr)] out string name);
    void GetAttributes(uint mask, out uint attrs);
    void Compare(IShellItem si, uint hint, out int order);
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr pbc,
      [MarshalAs(UnmanagedType.LPStruct)] Guid riid, out IShellItem item);
  public static string Pick(IntPtr owner, string title, string initial) {
    IFileDialog d = (IFileDialog)new FileOpenDialogRCW();
    uint fos; d.GetOptions(out fos);
    d.SetOptions(fos | 0x20 | 0x40);  // FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
    d.SetTitle(title);
    if (!String.IsNullOrEmpty(initial) && System.IO.Directory.Exists(initial)) {
      try {
        IShellItem start;
        SHCreateItemFromParsingName(initial, IntPtr.Zero, typeof(IShellItem).GUID, out start);
        d.SetFolder(start);
      } catch {}
    }
    if (d.Show(owner) != 0) return null;  // 취소
    IShellItem res; d.GetResult(out res);
    string path; res.GetDisplayName(0x80058000, out path);  // SIGDN_FILESYSPATH
    return path;
  }
}
"""


def native_pick(initial: str, title: str) -> str | None:
    """이 PC 의 기본 폴더 선택 창(Windows 탐색기 창 / macOS Finder 창)을 띄워 고른 폴더를 돌려준다. 취소하면 None.

    창은 프로그램이 도는 PC 화면에 뜬다. 창을 띄우지 못하면 RuntimeError.
    """
    initial = initial if initial and Path(initial).is_dir() else str(Path.home())
    env = {**os.environ, "LSATS_INIT": initial, "LSATS_TITLE": title}
    try:
        if WINDOWS:
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms\n"
                "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
                "$f = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}\n"
                "try {\n"
                "  Add-Type -TypeDefinition $env:LSATS_CS -Language CSharp\n"
                "  $p = [LsatsFolderPicker]::Pick($f.Handle, $env:LSATS_TITLE, $env:LSATS_INIT)\n"
                "} catch {\n"
                "  $d = New-Object System.Windows.Forms.FolderBrowserDialog\n"
                "  $d.Description = $env:LSATS_TITLE\n"
                "  $d.SelectedPath = $env:LSATS_INIT\n"
                "  $p = $null\n"
                "  if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) { $p = $d.SelectedPath }\n"
                "}\n"
                "if ($p) { Write-Output $p }\n"
            )
            enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
            cmd = ["powershell", "-NoProfile", "-STA", "-EncodedCommand", enc]
            env["LSATS_CS"] = _WIN_PICKER
        elif sys.platform == "darwin":
            script = (
                "on run argv\n"
                "  activate\n"
                "  try\n"
                "    set f to choose folder with prompt (item 2 of argv) default location (POSIX file (item 1 of argv))\n"
                "  on error number -128\n"  # 취소
                "    return \"\"\n"
                "  end try\n"
                "  return POSIX path of f\n"
                "end run"
            )
            cmd = ["osascript", "-e", script, initial, title]
        elif shutil.which("zenity"):
            cmd = ["zenity", "--file-selection", "--directory", f"--title={title}",
                   f"--filename={initial.rstrip('/')}/"]
        else:
            raise RuntimeError("이 PC 에서는 폴더 선택 창을 띄울 수 없어요. 경로를 직접 붙여 넣어 주세요.")
        r = subprocess.run(cmd, capture_output=True, env=env, timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"폴더 선택 창을 띄우지 못했어요: {e}") from e
    return r.stdout.decode("utf-8", errors="replace").strip() or None
