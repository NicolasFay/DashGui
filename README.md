# DashGui

## Raspberry Pi

* Model: Raspberry Pi 3 Model B+

### Connecting to Pi

Using an Ethernet to USB-C Connection to wire into the Pi

* SSH into the pi by typing into a terminal on your computer `ssh aero@raspberrypi.local`
    * answer yes to fingerprinting and enter the password to connect
* If this times out (takes a while or cannot find the Pi), try unplugging and replugging into the Pi
* If you get this message trying to ssh into the Pi:
    ```text
    njfay@ip0af51d24 ~ % ssh aero@raspberrypi.local
    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    @    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
    Someone could be eavesdropping on you right now (man-in-the-middle attack)!
    It is also possible that a host key has just been changed.
    The fingerprint for the ED25519 key sent by the remote host is
    SHA256:jOkgpVCrH8CudHGnBYLwIpOxzpGH0rneoowDbUUFwq8.
    Please contact your system administrator.
    Add correct host key in /Users/njfay/.ssh/known_hosts to get rid of this message.
    Offending ECDSA key in /Users/njfay/.ssh/known_hosts:12
    Host key for raspberrypi.local has changed and you have requested strict checking.
    Host key verification failed.
    ```
    * Enter into the terminal `ssh-keygen -R raspberrypi.local` to clear old rpi host keys that are cached


### Connecting Pi to Internet

To get the Pi on wifi turn on your phones hotspot

* Enable the setting **Maximize Compatibility**
* Keep your phone screen open on the hotspot setting
* Type into the ssh'd terminal `sudo nmcli device wifi connect "Your_iPhone_Name" password "Your_Hotspot_Password"`

## Software Maintenence

### External Watchdog Service File

If you ever change the location of the software in the Pi (what directory it is in), or make changes to how the external watchdog works then you want to update the service file and reload it. To do so:

* Update the file and run this while ssh'd into the Pi
    * `sudo systemctl daemon-reload`
    * And then `sudo systemctl restart dashboard.service`

## Virtual Environment Setup

Have python installed on your machine and in the command terminal:

1) Create virtual environment by running 
    * Mac: `python3 -m venv .venv`
    * Windows: `python -m venv .venv`
2) Activate Environment
    * Mac: `source .venv/bin/activate`
    * Windows: `.venv\Scripts\activate.bat`
3) Install required libraries to run
    * `pip install -r requirements.txt`
