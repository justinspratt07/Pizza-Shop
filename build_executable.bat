@echo off
setlocal

set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe

if not exist "%CSC%" (
    echo Could not find the Windows C# compiler.
    echo Install the .NET Framework developer tools or build with Visual Studio.
    exit /b 1
)

"%CSC%" /nologo /target:exe /out:PizzaShopLauncher.exe PizzaShopLauncher.cs
if errorlevel 1 exit /b 1

echo Built PizzaShopLauncher.exe
