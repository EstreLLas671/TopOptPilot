from topoptpilot_desktop.engineering.matlab import classify_runtime_root


def test_nested_release_name_is_ready_when_runtime_dll_and_uninstaller_are_both_present() -> None:
    root = r"C:\Program Files\MATLAB\MATLAB Runtime\R2025b\R2025b"
    files = {
        (root + r"\runtime\win64\mclmcrrt25_2.dll").lower(),
        (root + r"\bin\win64\Uninstall_MATLAB_Runtime.exe").lower(),
    }

    status = classify_runtime_root(root, file_exists=lambda value: value.lower() in files)

    assert status.state == "ready"


def test_runtime_dll_without_uninstaller_is_not_ready() -> None:
    root = r"C:\Program Files\MATLAB\MATLAB Runtime\R2025b"
    dll = (root + r"\runtime\win64\mclmcrrt25_2.dll").lower()

    status = classify_runtime_root(root, file_exists=lambda value: value.lower() == dll)

    assert status.state == "missing"
