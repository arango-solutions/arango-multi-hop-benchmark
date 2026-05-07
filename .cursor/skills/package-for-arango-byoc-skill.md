# Agent Skill: Package-for-Arango-BYOC

## Overview
This skill defines the technical standards and procedures for packaging custom code to be deployed on the Arango Contextual Data Platform using the Bring Your Own Code (BYOC) framework.

## 1. Technical Standards & Requirements
To ensure compatibility with the Container Manager, applications must meet the following:
* **Networking**: The service must expose an HTTP server on **Port 8000**.
* **Routing**: The application must handle requests at the **root path (`/`)**. 
* **Python Runtime**: Standard support is for **Python 3.13**. 
* **Dependency Management**: Use **`uv`** for Python projects. Specify dependencies in a `pyproject.toml` file.

## 2. Automated Packaging (ServiceMaker)
ServiceMaker is the recommended tool for automating the creation of deployment-ready artifacts.

**Workflow:**
* **Build Tool**: Clone the repository and run `cargo build --release`.
* **Execution**: Use `./servicemaker` with project parameters to start the build.
* **Locate Artifact**: Navigate to the project's folder within the `target` directory. Look for the project `.yml` file (e.g., `my-project-12345.yml`).
* **Deployment File**: The required artifact is the `project.tar.gz` file found in that directory.

## 3. Manual Packaging
If ServiceMaker is not used, packages must be created manually:
* **Structure**: Include a `pyproject.toml` and your application code (e.g., `main.py`).
* **Archive**: Create a gzipped tarball using: `tar -czf myservice.tar.gz <project_directory>/`.

## 4. Critical Troubleshooting & "Gotchas"
* **Architecture Mismatch**: If building on ARM64 (e.g., Apple Silicon) and the tool pulls AMD64 images, build the base image locally first.
    * **Fix**: Run `docker build -f Dockerfile.py13base -t arangodb/py13base:latest .` inside the `baseimages` directory.
* **Dependency Extras**: ServiceMaker does not currently support `uv sync --extra` packages. Ensure all required packages are moved into the main `dependencies` list in `pyproject.toml`.
* **Scoping**: Choose "Global" (hosted on `_system`) for platform-wide services or database-specific for isolated workloads.
* **Version Conflict**: To run multiple instances of the same version in one database, provide a unique `app_instance_name`.

## 5. Deployment Metadata
When uploading to the Container Manager, provide:
* **File Name**: The unique name for the service.
* **Version**: A semantic version number (e.g., 1.0.0).
* **Service URL Path**: The path where the service will be reachable (e.g., `my-project`).
