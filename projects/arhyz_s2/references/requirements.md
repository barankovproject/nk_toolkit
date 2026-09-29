# Environment Requirements

## Core software

| Component      | Version          | Notes                              |
|----------------|------------------|------------------------------------|
| Civil 3D       | 2024 (R24.3)     | Release 13.6.342.0, Russian locale |
| AutoCAD        | 2024 (R24.3)     | Base platform, release 24.3.61.0   |
| Dynamo         | 2.18.1.5096      | Bundled with Civil 3D 2024         |
| CPython        | 3.9.12           | Embedded via Python.Included.dll   |
| Python.Runtime | 2.5.2 (pythonnet)| .NET ↔ Python bridge               |
| .NET Framework | 4.8.1            | CLR v4.0.30319, release 533325     |
| OS             | Windows 10 Pro   | Build 19045                        |

## Dynamo geometry libraries

| Library         | Version       |
|-----------------|---------------|
| ProtoGeometry   | 2.18.0.1365   |

## Python packages bundled in Dynamo

These are available inside CPython nodes without installation:

| Package      | Version  |
|--------------|----------|
| numpy        | 1.24.1   |
| pandas       | 1.5.3    |
| matplotlib   | 3.6.3    |
| openpyxl     | 3.0.10   |
| Pillow       | 9.4.0    |
| contourpy    | 1.0.7    |
| fonttools    | 4.38.0   |

## Install paths

| Component | Path                                                 |
|-----------|------------------------------------------------------|
| AutoCAD   | `C:\Program Files\Autodesk\AutoCAD 2024\`            |
| Dynamo    | `C:\Program Files\Autodesk\AutoCAD 2024\C3D\Dynamo\` |
