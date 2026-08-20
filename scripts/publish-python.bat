@echo off
setlocal EnableExtensions

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul || exit /b 1

if /I "%~1"=="help" goto :usage
if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage
if not "%~1"=="" if /I not "%~1"=="build" if /I not "%~1"=="test-upload" if /I not "%~1"=="upload" goto :usage

set "BOOTSTRAP_PYTHON=C:\Python311\python.exe"
if not exist "%BOOTSTRAP_PYTHON%" set "BOOTSTRAP_PYTHON=python"
set "VENV_PYTHON=.venv-publish\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  echo Creating isolated publishing environment...
  "%BOOTSTRAP_PYTHON%" -m venv .venv-publish || goto :failure
)

echo Installing publishing tools...
"%VENV_PYTHON%" -m pip install --upgrade pip build twine || goto :failure

echo Removing previous Causentra build artifacts...
del /q "python\dist\causentra-*" 2>nul

echo Building Python distributions...
"%VENV_PYTHON%" -m build --outdir python\dist python || goto :failure

echo Checking package metadata...
"%VENV_PYTHON%" -m twine check python\dist\* || goto :failure

if /I "%~1"=="test-upload" goto :test_upload
if /I "%~1"=="upload" goto :upload

echo.
echo Build complete. Review python\dist before uploading.
echo Run "scripts\publish-python.bat test-upload" to publish to TestPyPI.
echo Run "scripts\publish-python.bat upload" to publish to PyPI.
goto :success

:test_upload
echo.
echo Uploading checked artifacts to TestPyPI. Twine will prompt for a TestPyPI token.
"%VENV_PYTHON%" -m twine upload --repository testpypi python\dist\* || goto :failure
goto :success

:upload
echo.
echo WARNING: PyPI uploads are public and version files cannot be replaced.
set "UPLOAD_CONFIRMATION="
set /P "UPLOAD_CONFIRMATION=Upload the checked artifacts to PyPI? [y/N]: "
if /I not "%UPLOAD_CONFIRMATION%"=="Y" goto :cancelled
"%VENV_PYTHON%" -m twine upload python\dist\* || goto :failure
goto :success

:cancelled
echo Upload cancelled.
popd >nul
exit /b 0

:success
echo.
echo Done.
popd >nul
exit /b 0

:failure
echo.
echo Publishing command failed. No upload was performed after the failed step.
popd >nul
exit /b 1

:usage
echo Usage: scripts\publish-python.bat [build^|test-upload^|upload]
echo.
echo   build        Build and validate only ^(default^).
echo   test-upload  Build, validate, then upload to TestPyPI.
echo   upload       Build, validate, then upload to real PyPI after confirmation.
popd >nul
exit /b 2
