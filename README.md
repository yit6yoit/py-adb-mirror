# **py-adb-mirror**

A lightweight Python-based Android screen mirroring tool that works by
capturing the device screen using `adb screencap`, pulling the image to
your computer, and displaying it in a browser.\
It also supports **touch input**, including taps and swipes, directly
from the web interface.

> **Note:** This project is **mostly AI-generated** and has been
> **tested on a cheap 4G Android 4.4 device** on **EndeavourOS**.\
> Performance depends heavily on device speed and USB connection
> quality. Aso this the my first project and i dont know if i did
> everything right.

------------------------------------------------------------------------

## **Features**

-   Screen mirroring via repeated `adb screencap`
-   Automatic pulling & cleanup of screenshots
-   Browser-based live view
-   Supports taps and swipe gestures
-   Flask backend with CORS enabled
-   Fully local execution

------------------------------------------------------------------------

## **Requirements**

### **Python Libraries**

Install the required libraries with:

``` bash
pip install flask flask-cors pillow
```

### **System Requirements**

-   `adb` must be available in your system PATH\
-   USB debugging must be enabled on your Android device\
-   Works on Linux/macOS/Windows

------------------------------------------------------------------------

## **Usage**

1.  Make sure `adb` is installed and accessible globally (test with
    `adb devices`).
2.  Connect your Android device via USB.
3.  Start the Python script:

``` bash
python main.py
```

4.  Open your browser and visit:

```{=html}
<!-- -->
```
    http://localhost:5000/

You should see your device's screen and be able to interact through taps
and swipes.

------------------------------------------------------------------------

## **Notes**

-   This method uses repeated screenshots, not video streaming ---
    expect lower fps.
-   Verified working with an old Android 4.4 device.
-   Ideal for debugging or simple remote control tasks.
-   For now probably doesnt automatically work with wireless debugging.
-   For me frame updating speed higher than 750ms doesnt work.
