# arxivscan

A simple script to get email notifications for new papers on [arxiv.org](https://arxiv.org).

## Installation and Setup

1. Clone the repository

```bash
git clone https://github.com/wimmerth/arxivscan.git
``` 

2. Install the required packages:

```bash
conda create -n arxivscan python=3.9
conda activate arxivscan
python -m pip install --upgrade pip
pip install arxiv
```

3. Create an app password for your gmail account (https://support.google.com/accounts/answer/185833?hl=en)
4. Add your gmail address and app password as environment variables and reactivate the environment:

```bash
conda env config vars set ARXIVSCAN_EMAIL=<your gmail address>
conda env config vars set ARXIVSCAN_PASSWORD=<your app password (16 digits)>
conda deactivate
conda activate arxivscan
```

5. Run the script:

```bash
python main.py
```

Optional arguments are:

- `--config`: Path to the config file (default: `config.json`)
- `--interests`: Lets you add interests to an existing config file in an interactive dialog
- `--on_startup`: Set this flag if you want to automatically run this script (with a given config) on startup of the
  local machine

6. If you want to run the script on startup, you can create a bash script with contents like this:

```bash
#!/bin/bash
source <absolute-path-to-conda>/etc/profile.d/conda.sh
conda activate arxivscan
python <absolute-path-to-this-directory>/main.py --config <path-to-your-config>.json --on_startup
```

and add it to your startup applications using crontab:

7. Open crontab:

```bash
crontab -e
```

8. Add the following line to the end of the file:

```bash
@reboot /bin/bash <absolute-path-to-your-bash-script>.sh
```

## Example Mail Notification

![img.png](img.png)