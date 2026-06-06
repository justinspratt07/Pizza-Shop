using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;

class PizzaShopLauncher
{
    private const string LocalUrl = "http://127.0.0.1:5000/";
    private static Process serverProcess;

    static int Main(string[] args)
    {
        string appDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string serverPath = Path.Combine(appDirectory, "server.py");
        string requirementsPath = Path.Combine(appDirectory, "requirements.txt");
        bool checkOnly = HasArgument(args, "--check");
        bool openBrowser = !HasArgument(args, "--no-browser");

        Console.Title = "PizzaShop Launcher";
        Console.WriteLine("PizzaShop Launcher");
        Console.WriteLine("------------------");

        if (!File.Exists(serverPath))
        {
            Console.WriteLine("Could not find server.py next to this launcher.");
            Console.WriteLine("Keep PizzaShopLauncher.exe in the same folder as server.py, templates, static, and data.");
            PauseIfNeeded(checkOnly);
            return 1;
        }

        PythonCommand python = ResolvePythonCommand();
        if (python == null)
        {
            Console.WriteLine("Python was not found. Install Python 3, then run this launcher again.");
            PauseIfNeeded(checkOnly);
            return 1;
        }

        Console.WriteLine("Using Python command: " + python.DisplayName);

        if (!EnsureFlaskAvailable(python, requirementsPath))
        {
            PauseIfNeeded(checkOnly);
            return 1;
        }

        Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs eventArgs)
        {
            eventArgs.Cancel = true;
            StopServer();
            Environment.Exit(0);
        };

        serverProcess = StartServer(python, appDirectory);
        if (serverProcess == null)
        {
            PauseIfNeeded(checkOnly);
            return 1;
        }

        Console.WriteLine("Starting PizzaShop server...");

        if (WaitForServer())
        {
            if (checkOnly)
            {
                Console.WriteLine("Server check passed.");
                StopServer();
                return 0;
            }

            if (openBrowser)
            {
                Console.WriteLine("Opening " + LocalUrl);
                OpenBrowser(LocalUrl);
            }
            else
            {
                Console.WriteLine("Server is ready at " + LocalUrl);
            }
        }
        else if (serverProcess.HasExited)
        {
            Console.WriteLine("The server stopped before it was ready.");
        }
        else
        {
            Console.WriteLine("The server is still starting. Open this URL when it is ready:");
            Console.WriteLine(LocalUrl);
        }

        Console.WriteLine();
        Console.WriteLine("Leave this window open while using PizzaShop.");
        Console.WriteLine("Press Ctrl+C to stop the server.");

        serverProcess.WaitForExit();
        return serverProcess.ExitCode;
    }

    private static PythonCommand ResolvePythonCommand()
    {
        PythonCommand[] commands = new PythonCommand[]
        {
            new PythonCommand("python", "", "python"),
            new PythonCommand("py", "-3", "py -3")
        };

        foreach (PythonCommand command in commands)
        {
            if (RunProcess(command.FileName, CombineArgs(command.BaseArgs, "--version"), AppDomain.CurrentDomain.BaseDirectory, true) == 0)
            {
                return command;
            }
        }

        return null;
    }

    private static bool EnsureFlaskAvailable(PythonCommand python, string requirementsPath)
    {
        int flaskCheck = RunProcess(
            python.FileName,
            CombineArgs(python.BaseArgs, "-c \"import flask\""),
            AppDomain.CurrentDomain.BaseDirectory,
            true);

        if (flaskCheck == 0)
        {
            return true;
        }

        if (!File.Exists(requirementsPath))
        {
            Console.WriteLine("Flask is not installed and requirements.txt was not found.");
            return false;
        }

        Console.WriteLine("Installing required Python packages...");
        int installResult = RunProcess(
            python.FileName,
            CombineArgs(python.BaseArgs, "-m pip install -r \"" + requirementsPath + "\""),
            AppDomain.CurrentDomain.BaseDirectory,
            false);

        if (installResult != 0)
        {
            Console.WriteLine("Dependency installation failed.");
            return false;
        }

        return true;
    }

    private static Process StartServer(PythonCommand python, string appDirectory)
    {
        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = python.FileName;
        startInfo.Arguments = CombineArgs(python.BaseArgs, "server.py");
        startInfo.WorkingDirectory = appDirectory;
        startInfo.UseShellExecute = false;
        startInfo.RedirectStandardOutput = true;
        startInfo.RedirectStandardError = true;
        startInfo.CreateNoWindow = false;

        Process process = new Process();
        process.StartInfo = startInfo;
        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
        {
            if (eventArgs.Data != null)
            {
                Console.WriteLine(eventArgs.Data);
            }
        };
        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
        {
            if (eventArgs.Data != null)
            {
                Console.WriteLine(eventArgs.Data);
            }
        };

        try
        {
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            return process;
        }
        catch (Exception error)
        {
            Console.WriteLine("Could not start the server: " + error.Message);
            return null;
        }
    }

    private static bool WaitForServer()
    {
        DateTime deadline = DateTime.Now.AddSeconds(30);

        while (DateTime.Now < deadline)
        {
            if (serverProcess.HasExited)
            {
                return false;
            }

            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(LocalUrl);
                request.Method = "GET";
                request.Timeout = 1000;

                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    if ((int)response.StatusCode < 500)
                    {
                        return true;
                    }
                }
            }
            catch
            {
                Thread.Sleep(500);
            }
        }

        return false;
    }

    private static void OpenBrowser(string url)
    {
        try
        {
            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = url;
            startInfo.UseShellExecute = true;
            Process.Start(startInfo);
        }
        catch (Exception error)
        {
            Console.WriteLine("Could not open the browser automatically: " + error.Message);
        }
    }

    private static int RunProcess(string fileName, string arguments, string workingDirectory, bool quiet)
    {
        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = fileName;
        startInfo.Arguments = arguments;
        startInfo.WorkingDirectory = workingDirectory;
        startInfo.UseShellExecute = false;
        startInfo.RedirectStandardOutput = quiet;
        startInfo.RedirectStandardError = quiet;
        startInfo.CreateNoWindow = true;

        try
        {
            using (Process process = Process.Start(startInfo))
            {
                if (quiet)
                {
                    process.StandardOutput.ReadToEnd();
                    process.StandardError.ReadToEnd();
                }

                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch
        {
            return -1;
        }
    }

    private static string CombineArgs(string baseArgs, string additionalArgs)
    {
        if (String.IsNullOrWhiteSpace(baseArgs))
        {
            return additionalArgs;
        }

        return baseArgs + " " + additionalArgs;
    }

    private static bool HasArgument(string[] args, string expected)
    {
        foreach (string arg in args)
        {
            if (String.Equals(arg, expected, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    private static void StopServer()
    {
        try
        {
            if (serverProcess != null && !serverProcess.HasExited)
            {
                serverProcess.Kill();
                serverProcess.WaitForExit();
            }
        }
        catch
        {
        }
    }

    private static void PauseIfNeeded(bool checkOnly)
    {
        if (!checkOnly)
        {
            Console.WriteLine();
            Console.WriteLine("Press Enter to close.");
            Console.ReadLine();
        }
    }

    private class PythonCommand
    {
        public readonly string FileName;
        public readonly string BaseArgs;
        public readonly string DisplayName;

        public PythonCommand(string fileName, string baseArgs, string displayName)
        {
            FileName = fileName;
            BaseArgs = baseArgs;
            DisplayName = displayName;
        }
    }
}
