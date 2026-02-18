# Installer Discovery Report

## Inputs
- Zip: `../../denodo/installable/denodo-express-install-9-linux64.zip`

## Detected core files
- install script: `denodo-install-9/install.sh`
- dat payload: `denodo-install-9/denodo-install-9.dat`

## install.sh summary
Saved to: `../runtime/discovery/install.sh`

## Candidate startup/entry scripts inside zip
Saved to: `../runtime/discovery/start_script_candidates.txt`

## Filtered strings from .dat payload
Saved to: `../runtime/discovery/dat_strings_filtered.txt`

## Recommended next steps
1. Review `../runtime/discovery/install.sh` for invocation of the .dat installer.
2. Review `../runtime/discovery/dat_strings_filtered.txt` for hints of silent/console/response-file options.
3. If still unclear, run a disposable interactive installer container once and capture a response file.
4. Set these vars once confirmed:
   - `denodo_run_installer_during_build: true`
   - `denodo_installer_script`
   - `denodo_install_root`
   - `denodo_installer_flags`
   - `denodo_env.DENODO_START_CMD`
