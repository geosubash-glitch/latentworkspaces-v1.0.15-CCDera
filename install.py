import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox

def install():
    try:
        # Check if latent.exe is currently running to prevent file lock / access denied errors
        try:
            tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq latent.exe"], capture_output=True, text=True)
            if "latent.exe" in tasks.stdout.lower():
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(
                    "Installation Blocked",
                    "Latent Studio is currently running.\n\n"
                    "Please close the application and run this installer again."
                )
                root.destroy()
                sys.exit(1)
        except Exception:
            pass

        # 1. Determine local appdata path
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            local_appdata = os.path.expanduser("~/AppData/Local")
        
        install_dir = os.path.join(local_appdata, "Latent")
        os.makedirs(install_dir, exist_ok=True)
        
        # 2. Determine where source files are located (PyInstaller temp dir or current dir)
        base_dir = sys._MEIPASS if hasattr(sys, "_MEIPASS") else os.path.dirname(os.path.abspath(__file__))
        
        src_exe = os.path.join(base_dir, "latent.exe")
        src_ico = os.path.join(base_dir, "app_logo.ico")
        src_png = os.path.join(base_dir, "app_logo.png")
        
        # Fallback check if running standalone script
        if not os.path.exists(src_exe):
            # Try to look in parent/current dir
            src_exe = os.path.abspath("latent.exe")
            src_ico = os.path.abspath("app_logo.ico")
            src_png = os.path.abspath("app_logo.png")
            
        if not os.path.exists(src_exe):
            raise FileNotFoundError("Could not find latent.exe source file to install.")
            
        dest_exe = os.path.join(install_dir, "latent.exe")
        dest_ico = os.path.join(install_dir, "app_logo.ico")
        dest_png = os.path.join(install_dir, "app_logo.png")
        
        # 3. Copy files to destination
        shutil.copy2(src_exe, dest_exe)
        if os.path.exists(src_ico):
            shutil.copy2(src_ico, dest_ico)
        if os.path.exists(src_png):
            shutil.copy2(src_png, dest_png)
            
        # 4. Create Desktop Shortcut via PowerShell
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop_path, "Latent Studio.lnk")
        
        ps_cmd = (
            f'$WshShell = New-Object -ComObject WScript.Shell; '
            f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}"); '
            f'$Shortcut.TargetPath = "{dest_exe}"; '
            f'$Shortcut.WorkingDirectory = "{install_dir}"; '
            f'$Shortcut.IconLocation = "{dest_ico}"; '
            f'$Shortcut.Save()'
        )
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, check=True)
        
        # 5. Create Start Menu Shortcut
        start_menu_programs = os.path.join(local_appdata, "Microsoft", "Windows", "Start Menu", "Programs")
        start_menu_shortcut = os.path.join(start_menu_programs, "Latent Studio.lnk")
        
        ps_cmd_start = (
            f'$WshShell = New-Object -ComObject WScript.Shell; '
            f'$Shortcut = $WshShell.CreateShortcut("{start_menu_shortcut}"); '
            f'$Shortcut.TargetPath = "{dest_exe}"; '
            f'$Shortcut.WorkingDirectory = "{install_dir}"; '
            f'$Shortcut.IconLocation = "{dest_ico}"; '
            f'$Shortcut.Save()'
        )
        subprocess.run(["powershell", "-Command", ps_cmd_start], capture_output=True, check=True)
        
        # Show GUI completion screen
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "Installation Complete",
            "Latent Studio has been successfully installed!\n\n"
            "• Installed to: AppData\\Local\\Latent\n"
            "• Shortcut created on your Desktop\n"
            "• Shortcut added to your Start Menu"
        )
        root.destroy()
        
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Installation Failed",
            f"An error occurred during installation:\n{str(e)}"
        )
        root.destroy()
        sys.exit(1)

if __name__ == "__main__":
    install()
