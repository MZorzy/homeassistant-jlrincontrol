This component provides integration to the JLR InControl functionality to homeassistant. 

# Functionality
**Currently this loads a series of sensors for**
* Vehicle Info
* Alarm
* Doors
* Windows
* Tyres
* Range
* Location
* EV Battery Sensor (EVs only)
* Service Info

Each sensor has a series of attributes to show related sensor information.  Which attributes are show is dependant on support by your vehicle.

**And has services for**
* Update Health Status (forces update from vehicle)
* Honk/Flash
* Lock/Unlock
* Start Engine/Stop Engine
* Start Charging/Stop Charging
* Reset Alarm
* Start Preconditioning/Stop Preconditioning
* Set Max Charge (Always and One Off)

**Note:** Not all services are available on all models and the error log will show this if not available on your vehicle.

**Note 2**: When calling a service, HA will monitor the status of the service call and report in the error log if it failed.  Debug log will show this checking and the success/failure reason.


# Sample Images
![](https://raw.githubusercontent.com/msp1974/homeassistant-jlrincontrol/master/docs/panel1.png)


# Configuration
## Additional Optional Parameters

**Required Parameters**
```
jlrincontrol:
  username: <your InControl email address>
  password: <your InControl password>
```
**Optional Parameters**
1. scan_interval - in minutes. Default update interval is 5 minutes.  Use this to change that.  Minimum is 1 minute.
2. pin - set this to be able to use the lock/unlock on the lock sensor.
3. distance_unit - set this to 'mi' or 'km' to override the HA default metric for milages (mainly for funny UK system of miles and litres!).
4. health_update_interval - see vehcile health status update section
5. debug_data: - see debugging below.
```
  scan_interval: 5
  pin: <your InControl pin>
  distance_unit: <mi or km to override HA defualt>
  health_update_interval: 60
  debug_data: <false or true - see debugging>
```

# Vehicle Health Status Update

This integration has the ability to perform a scheduled health status update request from your vehicle.  By default this is disabled.  Adding the entry to your configuration.yaml as above will enable it (after a HA restart).

I do not know the impact on either vehicle battery or JLRs view on running this frequently, so please use at your own risk.  I would certainly not set it to too low an interval.

Alternatively, you can make a more intelligent health update request automation using the service call available in this integration and the output of some sensors.

I.e. on EV vehicles you could only call it if the vehicle is charging, or on all vehicles, only call it during the day and it was more than x period since the last update.

### Known Issues
* Only works for first vehicle on account.
* Some distance sensors do not show in local units (on list to fix).
* Service Info sensor shows ok even if car is needing service or adblue top up (on list to fix)
* Tyre pressures seem to be in inconsistant units between models and therefore give strange reading.
* Tyre pressures are not in local units.

# Debugging
1. To enable debug logging for this component, add the following to your configuration.yaml
```
logger:
  default: critical
  logs:
    custom_components.jlrincontrol: debug
```

2. To enable logging of the attributes and status data in the debug log, add the following to you configuration.yaml.
```
jlrincontrol:
  username: <your InControl email address>
  password: <your InControl password>
  debug_data: true
```

# More Information
For more information please see the [Readme.md](https://github.com/msp1974/homeassistant-jlrincontrol/blob/master/Readme.Md)
