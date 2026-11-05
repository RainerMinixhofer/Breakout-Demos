# Python files for the TMF8829 device (Linux native I2C)

Python version 3.10.11 or higher is required.

## Virtual environment

Recommendation is to set up a virtual environment.
To install a virtual environment named env, and use it:
```sh
python -m venv env
source env/bin/activate
```

## Requirements

To run the scripts in this folder you need to install the packages in the requirements.txt file with:    
pip install -r requirements.txt

All needed python packages are in the subdirectory packages.

## Folder and sub-folders:

### ./packages
Needed python packages.


### ./tmf8829
All python classes, files and functions, specific to the TMF8829.

##### tmf8829_application.py, tmf8829_application_common.py and tmf8829_bootloader.py:
The application and bootloader classes have the functionality to control the device hardware and the bootloader and also allows to download intel hex files to the device, measurements and the reading of result and histogram frames.

##### tmf8829_application defines.py:
Application specific defines and structures.

##### tmf8829_conv.py:
Contains convenience functions.
`createTmf8829()` uses the native Linux `/dev/i2c-*` backend.
If your system has multiple I2C buses, set one of these environment variables before running examples:
- `TMF8829_I2C_DEVICE` (for example `/dev/i2c-1`)
- `TMF8829_I2C_BUS` (for example `1`)

#### Python register files

##### tmf8829_host_regs.py
The registers of the TMF8829 for I2C communication.

##### tmf8829_application_registers.py:
Application specific registers.

##### tmf8829_config_page.py:
Application configuration register page.

### ./tmf8829/examples
Several examples that show the usage of how to:
- use the application printer to see results/frames in the terminal
- visualize pixel results or histograms 
- log data into a file with json format.
All examples use the native Linux I2C backend.
`example_visualisation_pixel_map.py` supports `--frontend pyplot` (default) and `--frontend flask`.

### ./tmf8829/utilities

##### tmf8829_application_printer.py:
The application printer class supports the printing of the results and histogram frames.

##### tmf8829_json_2_csv.py
Convert log files from json format to csv format

##### tmf8829_logger_service.py
Provides functionality to dump the data into a file with json format or to log data into a textfile.


##### tmf8829_visualisation.py
Functionality to visualize pixel data or histograms.