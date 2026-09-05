# User Manual — AeroGreenHouse

> [🇮🇹 Italiano](User_Manual.md) · 🇬🇧 English
>
> This is the manual for **the people who use** the greenhouse. No programming knowledge is
> required, and there is nothing to install or type: you look, you press, you read.
> If you are looking for how the software works inside, the document is
> [`DOCUMENTATION_EN.md`](DOCUMENTATION_EN.md).

---

## Contents

1. [What this program is](#1-what-this-program-is)
2. [Starting and stopping](#2-starting-and-stopping)
3. [Finding your way around](#3-finding-your-way-around)
4. [How to read a value](#4-how-to-read-a-value)
5. [Summary](#5-summary)
6. [Configuration](#6-configuration)
7. [Active processes](#7-active-processes)
8. [Jobs](#8-jobs)
9. [Environment](#9-environment)
10. [Climate](#10-climate)
11. [H2O](#11-h2o)
12. [Spectrum](#12-spectrum)
13. [Growth](#13-growth)
14. [Camera](#14-camera)
15. [Log](#15-log)
16. [When something goes wrong](#16-when-something-goes-wrong)
17. [Routine maintenance](#17-routine-maintenance)
18. [Frequently asked questions](#18-frequently-asked-questions)
19. [Glossary](#19-glossary)

---

## 1. What this program is

AeroGreenHouse is the **control panel of a greenhouse**. The greenhouse grows plants without
soil: the roots sit in a closed chamber and receive water and nutrients from a pump, at
regular intervals.

The program does three things:

1. **Controls** what switches itself on and off — the water pumps and the air conditioner.
2. **Measures** the air, the water and the plants, at intervals you choose.
3. **Stores and displays** everything it has measured: on screen, in an archive and, if
   configured, on a website.

### The parts of the greenhouse, one sentence each

| Part | What it is | Where you see it in the program |
|---|---|---|
| The **computer** | a small always-on computer running this program | it is the machine in front of you |
| The **probe box** | a small electronic box connected to the computer by a USB cable, with the water probes and the distance meters attached to it | **Configuration** screen, "Arduino boards" panel |
| The **pumps** | they bring water to the roots and switch on by themselves | **Jobs** screen |
| The **air sensor** | measures temperature and humidity | **Environment** screen |
| The **air conditioner** | switched on and off by the program through an infrared remote | **Climate** screen |
| The **water probes** | two probes immersed in the nutrient solution: one measures acidity, the other concentration | **H2O** screen |
| The **distance meters** | two small ultrasonic sensors: one looks at the water in the tank, the other looks down at the plants | **H2O** and **Growth** screens |
| The **spectrometer** | measures the colour of the light reflected by the leaves, to tell whether the plant is doing well | **Spectrum** screen |
| The **camera** | takes photos of the plants at regular intervals | **Camera** screen |

> **One thing worth knowing straight away.** The water probes and the distance meters are
> **not** attached to the computer: they are attached to the probe box, which in turn is
> attached to the computer by **a single USB cable**. If that cable comes loose, those four
> measurements stop working **all at once**, while temperature, humidity, photos and the
> spectrometer keep going. It is the first thing to check when something is wrong.

---

## 2. Starting and stopping

### Starting the program

Open the program and wait a few seconds: a window appears with a **dark strip of icons down
the left-hand side** and the content on the right.

The first thing you see is the **Summary**, already full of numbers. They are not
freshly-taken measurements: they are the **last known measurements**, read back from the
archive. Next to each one is its date, precisely so that you can tell whether it is five
minutes old or three days old.

### Closing the program

Closing the window **stops everything**: the automatic readings, the pumps driven by the
program, the upload to the website. Nothing keeps running out of sight.

Measurements already taken are **never lost**: they are saved to disk as they are taken. When
you reopen the program you find everything again.

> **Worth repeating:** if the greenhouse has to run on its own, the window must be **left
> open**. Closing it is like switching off the control panel.

---

## 3. Finding your way around

### The side bar

On the left there is a column of icons: these are the **eleven screens** of the program. Press
one and the content on the right changes. Nothing is lost by switching screens: readings in
progress keep running.

| Icon | Name | What it is for |
|---|---|---|
| ▦ | **Summary** | the state of the whole greenhouse at a glance |
| ⚙ | **Configuration** | every setting: how often to measure, which values count as good, where the probes are plugged in |
| ◉ | **Processes** | which automatic tasks are running right now |
| ⚡ | **Jobs** | the pumps: when they switch on and for how long |
| 🌡 | **Environment** | temperature, humidity and the daily summary |
| ❄ | **Climate** | automatic control of the air conditioner |
| 💧 | **H2O** | how much water is in the tank and what it is like (acidity and concentration) |
| ◐ | **Spectrum** | the plant health index |
| 🌱 | **Growth** | how tall the plants are and how they grow over time |
| 📷 | **Camera** | the photos |
| ☰ | **Log** | the program's diary and the **list of errors** |

At the top you find the screen title, a line explaining what it is for, and the **clock**.

### Colours, everywhere in the program

| Colour | Meaning |
|---|---|
| 🟢 **Green** | working / active / the value is the desired one |
| 🟠 **Orange** | attention: the value is approaching a limit |
| 🔴 **Red** | stopped, or a value outside the range you marked as acceptable |
| ⚪ **Grey** | no measurement available |

### The three buttons you find almost everywhere

Almost every measurement screen has the same three buttons. It is worth learning them once:

| Button | What it does |
|---|---|
| **📊 Read Now** (or *Measure Now*) | takes **one** measurement, immediately, and stops. Useful to check that a probe works |
| **▶️ Start Reading** | starts **automatic, repeated** measurement: from now on the program measures by itself, at the interval set in Configuration. The first measurement starts immediately |
| **⏹️ Stop Reading** | stops the automatic measurement. The effect is immediate, even if the next check was due in a day's time |

> **The distinction that matters:** *Read Now* is a snapshot, *Start Reading* is surveillance.
> To make the greenhouse run on its own, what you need is **Start Reading**.

---

## 4. How to read a value

### The arc indicators

Several values are shown as a **semicircular arc**, with a needle and the number in the
middle. The arc fills from left to right and tells you **where you are relative to the
maximum**.

The arc may carry **coloured bands**: they mark the range you declared desirable in
Configuration. If the needle is inside the green band, that value is fine.

Arcs are used only where a meaningful maximum exists (humidity runs 0 to 100 %, the tank from
empty to full). Plant height, which has no maximum, is shown as a plain number.

### The date under every value

Under each measurement there is **when it was taken**. After the number itself, it is the most
important piece of information on the screen: a perfect pH measured three days ago says
nothing about today's water.

If you read **"No measurement"**, that probe has never been read: start the reading, or press
*Read Now*.

### The status pills

Under certain values a **coloured pill** appears with a word: *Within range*, *Out of range*,
*No measurement*. It is the plain-language translation of the comparison between the
measurement and the limits you set.

---

## 5. Summary

This is the starting screen and it answers a single question: **how is the greenhouse right
now?**

It is divided into panels:

- **Environment** — air temperature, humidity and VPD (VPD is explained in §9).
- **H2O** — acidity (pH) and concentration (conductivity) of the water. This panel has **two
  separate dates**, one per probe: they are two independent measurements, taken at different
  times.
- **Tank** — how much water is left.
- **MCARI2 index** — how well the plants are doing according to the spectrometer.
- **Growth** — the height at the last measurement.
- **Active Processes** — the list of what is running automatically **right now**. If an
  automatic task is not started, it does not appear here at all.

This screen **measures nothing**: it only shows values collected by the others. If a number is
old, it is because automatic reading of that quantity is not active.

---

## 6. Configuration

Everything is set here. It is the only screen where **what you type has no effect until you
press Save**.

> ⚠️ **Always press "Save Configuration" at the bottom of the page.** If you switch screens
> without saving, your changes are lost without warning.

The page is divided into panels, one per topic. Each contains fields to fill in; scroll down
to see them all.

### What you set, panel by panel

| Panel | The settings you will use most |
|---|---|
| **Air (T/H)** | how many seconds between temperature and humidity readings |
| **Water — pH and conductivity** | how often to measure pH and conductivity (separately), and **which values count as good**: minimum and maximum pH, minimum and maximum conductivity |
| **Tank** | the size of the tank, how many litres of reserve should raise an alarm, how often to check the level |
| **Growth** | how many days between height measurements, how many readings to take each time |
| **Spectrometer** | how often to measure the health index |
| **Camera** | how many hours between photos |
| **Climate** | the temperature and humidity above which the air conditioner switches on |
| **Arduino boards** | where the probes are plugged in (see below) |

### The "Arduino boards" panel

This panel describes **the probe box**: which socket of the computer it is connected to, and
which terminal each probe is plugged into. It looks technical, but in everyday use you need it
on only two occasions: first installation, and whenever a cable is moved.

**If the box has never been configured**, or if the program says it cannot find it:

1. Check that the USB cable is plugged in at both ends.
2. Press **🔍 Detect boards**. The program lists the connected devices.
3. Select the one that appeared (there is usually only one).
4. Press **Save Configuration**.

Below there is one row per probe:

| Probe | What you must enter |
|---|---|
| **pH** | the terminal it is plugged into (normally `A0`) |
| **EC** (conductivity) | the probe's identification number (normally `100`) |
| **US_water** (tank distance meter) | the two terminals, "TRIG" and "ECHO" |
| **US_plant** (plant distance meter) | the other two terminals, "TRIG" and "ECHO" |

The numbers must match **where the cables are actually plugged in**. If you are not sure, do
not guess: there is a way to check, and it is the next button.

### The "Test" button

Next to each probe there is a **Test** button. Press it: the program asks that probe for a
measurement *right now* and tells you how it went.

| What it answers | What it means | What you do |
|---|---|---|
| A sensible number | everything is fine | nothing, you are done |
| «invalid pins» | the terminals you entered do not exist or are wrong | correct the numbers and try again |
| «unreliable reading» | the terminals are valid but the probe does not answer | check that the probe cable is fully inserted and that the probe is immersed |
| «board unreachable» | the problem is not the probe, it is the USB cable | reconnect the cable, then «Detect boards» |

This button is the quickest way to check a connection: you do not have to start anything, nor
wait for the next automatic check.

### A note you will find in the Tank and Growth panels

Under those two panels it says that the terminals of the distance meters are set in the
"Arduino boards" panel. This is not an oversight: **all** connections to the probe box live in
one single place, so you never have to look for them in two different spots.

---

## 7. Active processes

A list of indicator lights, one per automatic task, refreshed every second.

- 🟢 **green** = running;
- 🔴 **red** = stopped.

Red **does not mean broken**: it means "you have not started it" or "you stopped it". It is
perfectly normal for almost everything to be red right after opening the program: automatic
tasks must be started from their own screens.

Note that **pH and EC have two separate lights**: they are independent, and you can keep only
one of them running.

If you started something and the light stays red, the explanation is in the **Log** screen, at
the bottom, in the "Reading errors" section.

---

## 8. Jobs

"Job" is the name the program gives to **an automatic, repeated switch-on**: typically a pump.
A job states three things: *what* to switch on, *how often*, and *for how long*.

The two jobs already present are:

- **AEROPONICS** — misting of the roots;
- **IDROPONICS** — water recirculation.

The table shows, for each one, the interval, the duration and whether it is active.

| Button | What it does |
|---|---|
| **➕ New Job** | creates an automatic switch-on for another device |
| **✏️ Edit Job** | changes the interval and duration of the selected one |
| **🗑️ Delete Job** | removes it |
| **✅ Activate Job** | puts it into service: from now on it switches on by itself |
| **❌ Deactivate Job** | stops it |
| **🔄 Reload List** | re-reads the list |

To change something: **select the row first** in the table, then press the button.

> ⚠️ **Beware of the two times, which use different units.** The *interval* is in **minutes**
> (how often it switches on again), the *duration* is in **seconds** (how long it stays on).
> Swapping them means irrigating for twenty minutes instead of five seconds.

---

## 9. Environment

### The top part: the air right now

Three values, all taken together from the same sensor:

- **Temperature** in degrees;
- **Humidity** as a percentage;
- **VPD** — the least familiar of the three, and the most useful.

> **What VPD is, without formulas.** It is **how thirsty the air is**: how much more vapour it
> could still absorb before being saturated. Warm, dry air has a high VPD and "pulls" water
> out of the leaves; cold, humid air has a low VPD and does not pull at all.
>
> It matters because neither temperature nor humidity alone says how *the plant* experiences
> the air: 60 % humidity at 30 °C and 60 % at 15 °C are completely different situations for a
> leaf. VPD tells them apart in a single number.
>
> In practice: **too high** → the plants transpire more than they take up and suffer;
> **too low** → they stop transpiring, and with transpiration the transport of nutrients
> stops too.

The three buttons are the usual ones: *Read Now*, *Start Reading*, *Stop Reading*.

### The bottom part: the daily summary

Below there is the **daily processing**: once a day the program reads all the measurements of
the last 24 hours and produces averages, minimums, maximums and a **trend chart**.

The buttons **▶️ Start Daily** and **⏹️ Stop Daily** start and stop this automatic summary. It
is also the summary that gets published online, if the website is configured.

---

## 10. Climate

The program can switch the air conditioner on and off by itself, using an infrared remote: a
small emitter in the greenhouse imitates the original remote control.

| Button | What it does |
|---|---|
| **▶️ Start AC Control** | from now on the program decides by itself when to switch on and off |
| **⏹️ Stop AC Control** | it stops intervening; the air conditioner stays as it is right now |

A pill shows **▶ ACTIVE** or **⏹ INACTIVE**, and the last command sent to the air conditioner
is displayed with its time.

**The rule it follows**, in plain words: if the temperature rises above the maximum you set in
Configuration, or the humidity does, the air conditioner is switched on. It stays on for at
most the time you specified, then it is switched off anyway: this prevents it from running for
hours if something is off. The evaluation is repeated at regular intervals.

> If the last command is hours old and control shows as active, it simply means there has been
> no need to intervene.

---

## 11. H2O

The water screen, divided into **three independent panels**. Each has its own three buttons,
and each starts and stops on its own.

### Panel 1 — Tank level

How much water is left. The main value is the **volume in litres**; next to it you find the
fill percentage and the water height.

The measurement is taken by a distance meter mounted above the water: it measures **how far
away the surface is**, and from that the program works out how much water there is. For the
arithmetic to work, the tank dimensions must be correct in Configuration.

When the volume falls below the reserve you set, the program reports it in the diary. **That
is the moment to top up.**

### Panel 2 — Water pH

> **What pH is.** It is **how acidic the water is**. The scale runs from 0 to 14: 7 is
> neutral, below is acidic, above is basic. In soil-free growing pH is decisive for one
> specific reason: **if it is wrong, the plants cannot take up the nutrients even though they
> are there**. You can have a perfect solution and starving plants.
>
> The desired value for most crops is between **5.5 and 6.5** — these are the preset limits in
> Configuration, and you can change them.

The value appears large in the centre, with a pill saying whether it is within range and the
date of the last measurement.

**If the pH is out of range:** this is not a fault, it is an agronomic indication. You correct
it by adding a small amount of adjuster to the solution (*pH-* to lower it, *pH+* to raise
it), stirring well and measuring again after a few minutes with *📊 Read Now*. Always a little
at a time: pH moves more than you expect.

> ⏱️ **A pH measurement takes about 8 seconds.** This is normal: the probe needs to settle,
> and the program waits on purpose. If nothing happens for a few seconds after pressing *Read
> Now*, do not press again.

### Panel 3 — Electrical conductivity

> **What conductivity (EC) is.** It is **how concentrated the solution is**: how many nutrient
> salts are dissolved in it. Pure water does not conduct electricity; the more salts it
> contains, the more it conducts. By measuring how well it conducts, you know how "rich" it
> is.
>
> Too low: the plants are hungry. Too high: the solution is so concentrated that the roots can
> no longer take up water — and the plant wilts even though it is sitting in water.

This panel shows **three numbers**, all coming from a single measurement:

| Value | Unit | What it says |
|---|---|---|
| **Conductivity** | µS/cm | the main value, the one to compare with the limits |
| **TDS** | ppm | the same salts expressed as "how many milligrams per litre": the same thing in a different unit, used by many fertilisers |
| **Salinity** | PSU | how salty the solution is |

They are not three separate measurements: they are three ways of saying the same thing, which
is why they always appear and update together.

**If conductivity is out of range:** too high → dilute by adding water; too low → add
fertiliser. In both cases a little at a time, stir and measure again. After correcting the
concentration it is worth **checking the pH as well**, because fertiliser shifts it.

---

## 12. Spectrum

The spectrometer looks at the light reflected by the leaves and turns it into a single number
between 0 and 1, the **MCARI2 index**. Put simply: **healthy leaves reflect light differently
from suffering leaves**, and this instrument notices before the problem is visible to the eye.

A coloured pill translates the number into a phrase:

| Colour | State | What it means |
|---|---|---|
| 🔴 Red | **Stress** | possible lack of water or nutrients (often nitrogen) |
| 🟠 Orange | **Borderline** | keep an eye on it |
| 🟢 Light green | **Healthy** | all good |
| 🟢 Dark green | **Very healthy** | no deficiency detected |

Below you find the **history** of the last measurements: it is more useful than a single
value, because what matters is the **trend**. An index falling day after day signals a problem
long before the leaves change colour.

The buttons are **🔬 Measure Now**, **▶️ Start Reading** and **⏹️ Stop Reading**.

> **How to take a meaningful measurement.** The instrument must always be held at the **same
> distance and the same angle** to the leaves, and if possible under the same ambient light.
> Measurements taken under different conditions are not comparable, and the index is only
> meaningful when compared with the previous days'.

---

## 13. Growth

How tall the plants are. The measurement is taken by a distance meter mounted **above** the
plants and pointing down: it measures how far away the top is and, knowing how high the
starting point is, works out the height.

On the screen you find the height at the last measurement, its date, a **chart** of the trend
over time and a table with all the measurements.

| Button | What it does |
|---|---|
| **📏 Measure Now** | a single measurement |
| **▶️ Start Reading** | automatic measurement, normally once a day |
| **⏹️ Stop Reading** | stops the automatic measurement |
| **📐 Calibration** | tells the program where "zero" is — see below |

### Calibration: do it once, and do it properly

The program does not know by itself where the plants end and the shelf begins. You have to
teach it **once**, at the start, and from then on all measurements are counted from there.

**Procedure:**

1. Do it **before the plants have grown**, or in any case with the measuring area clear.
2. Remove anything under the sensor that is not the reference surface.
3. Make sure automatic measurement is **not** running: if it is, press *⏹️ Stop Reading*
   first. The program refuses to calibrate while it is measuring — that is a safeguard, not a
   malfunction.
4. Press **📐 Calibration** and confirm.
5. The program measures the current distance and stores it as "zero height".

After calibration, a measurement taken immediately must read **0 cm**. If it reads anything
else, something had been left under the sensor: repeat.

> ⚠️ **Why it is worth being careful.** A mistake in this step carries over **identically to
> every future measurement**: if zero is 3 cm off, every height will be 3 cm off, for ever,
> and no chart will reveal it. It is the one operation in the program where being fussy pays.

If you move the sensor, or change the height of the shelf, **calibration must be repeated**.

---

## 14. Camera

Photos of the plants, so you can see over weeks what you do not notice day by day.

| Button | What it does |
|---|---|
| **▶️ Start acquisition** | begins taking photos by itself, every N hours (N is set in Configuration) |
| **⏹️ Stop acquisition** | stops |
| **📷 Start camera** | shows the **live view**, so you can frame the shot. The same button switches it off |

Below you see the **last photo taken**, with date and time.

> **The two functions cannot both be on.** There is only one camera and it cannot be used by
> two things at once: if you try to start the live view while automatic shots are running, the
> program tells you instead of freezing. Switch one off, switch the other on.

Typical use: start the live view, adjust the framing, switch the live view off, start the
automatic shots.

---

## 15. Log

Two parts, and the second is the one that really matters to you.

### At the top: the diary

Everything the program does, line by line, in real time: successful readings, pumps switched
on, commands to the air conditioner. Lines are colour-coded — red for errors, orange for
warnings. It is mostly useful when you have to tell someone else what happened.

### At the bottom: **Reading errors**

This section lists **only the times a probe could not be read**, with:

- **when** it happened;
- **which probe** (`pH`, `EC`, `US_water` = tank, `US_plant` = plants);
- **a plain-language sentence** explaining the cause and, almost always, what to do.

The messages are written to be read by whoever runs the greenhouse, not by a technician: they
say things like *«check that the USB cable is connected»* or *«correct them in the
Configuration screen»*.

The list **refreshes itself** every couple of seconds: an error appears without you having to
do anything. There is a **🔄 Refresh errors** button as well.

The errors **survive closing and reopening** the program: when you reopen it, today's errors
are still there.

> **If a light is red and you do not understand why, this is the section to look at.** In
> practice it is the only diagnostics page you need to know.

A note on what you will **not** find here: a tank in reserve or a pH out of range are not
reading errors — they are successful measurements that say something unwelcome. They appear in
the diary above and in their own screens, not in this list.

---

## 16. When something goes wrong

### The messages you may read, and what to do about them

| What you read | What it really means | What to do |
|---|---|---|
| «board unreachable ... check that the USB cable is connected» | the computer cannot find the probe box | reconnect the USB cable at both ends; wait about ten seconds; then Configuration → **🔍 Detect boards** → **Save** |
| «no answer ... within 15 seconds» | the box is connected but does not answer: it has probably locked up | unplug and replug the USB cable, wait a few seconds, try again with **Test** |
| «invalid pins ... correct them in the Configuration screen» | the terminals given for that probe do not match | Configuration → "Arduino boards" → correct that probe's numbers → **Save** → **Test** |
| «unreliable reading, check the probe connection» | the connections are right but the probe gives no sensible value | check that the probe cable is fully inserted and that the probe is immersed (pH and EC) or that nothing is blocking the distance meter |
| «value ... outside the 0-14 scale» (pH) | this is not a measurement, it is a fault | the probe is disconnected or broken: check the cable, then **Test** |
| «distance ... outside the operating range (2-400cm)» | the distance meter sees something too close, or nothing at all | remove obstacles, check that the sensor points where it should |
| «no Arduino board configured for...» | that probe has never been declared | Configuration → "Arduino boards" → fill in its fields → **Save** |
| «pH OUT OF RANGE» / «EC OUT OF RANGE» | **not a fault**: the measurement succeeded, you just do not like the value | correct the nutrient solution (§11) |
| «LOW WATER ... refill the tank» | **not a fault**: the tank is in reserve | top it up |

### If no water or distance measurement works at all

Four probes failing together = **almost certainly the USB cable**. Check that first, before
touching any setting. Temperature, humidity, photos and the spectrometer still working
confirms the diagnosis: those do not go through the box.

**There is no need to restart the program**: as soon as the box is reachable again, the next
reading resumes by itself.

### If a value stays stuck on an old number

That is not a fault: automatic reading of that quantity has not been started. Go to its screen
and press **▶️ Start Reading**. To check whether anything is actually broken, try **📊 Read
Now** first.

### If you changed a setting and nothing happened

Did you press **Save Configuration**? It is the most common mistake. After saving, the changes
take effect immediately and **there is no need to restart the program**, not even after
changing a connection.

---

## 17. Routine maintenance

| How often | What to do |
|---|---|
| **Every day** | a glance at the Summary: are the measurement dates recent? Is there still water in the tank? |
| **Every day** | a glance at "Reading errors" at the bottom of the Log screen |
| **Every week** | rinse the pH and EC probes with clean water and dry them gently, without rubbing the tip |
| **Every week** | check that no leaves, condensation or cobwebs are in front of the two distance meters |
| **About every month** | have the pH and EC probes recalibrated |
| **At every change of growing cycle** | redo the growth calibration (§13) |

### Calibrating the pH and EC probes

This is the one operation that is **not done from the screens described in this manual**. It
needs someone able to work with the probe box directly, and it needs specific materials:

- for **pH**: buffer solutions at pH 7, pH 4 and pH 10;
- for **EC**: reference solutions of known conductivity.

Probes gradually lose accuracy with use: without periodic recalibration they keep producing
numbers, but numbers that are less and less true. **If the measured values do not match what
you expect, the prime suspect is calibration, not the plant.**

Ask whoever installed the system: the procedure is described in the technical documentation.

---

## 18. Frequently asked questions

**Do I have to leave the window open all the time?**
Yes, if you want the automatic readings and the pumps to keep running. Closing the window
stops everything.

**If the power goes out, do I lose data?**
No. Measurements are saved to disk as soon as they are taken. When power returns you find
everything again, and today's errors are still in the list. You do, however, have to
**restart the automatic readings**: they do not resume by themselves.

**Can I keep only pH running and not conductivity?**
Yes. Each measurement starts and stops on its own.

**I pressed "Read Now" for pH and nothing happens.**
Wait about ten seconds: that measurement takes roughly 8 seconds. Do not press repeatedly.

**I moved the plant sensor. Do I need to do anything?**
Yes: redo the growth calibration (§13). Otherwise every future height will be wrong by the
same amount.

**I moved a probe cable to a different terminal.**
Update the terminals in Configuration → "Arduino boards", **Save**, then check with **Test**.
No restart needed.

**What does a red light mean?**
That the automatic task is not running. If you thought you had started it, look at "Reading
errors" in the Log screen.

**The pH value is out of range: is something broken?**
No. It is a successful measurement telling you the water needs correcting. A fault produces a
message in "Reading errors", not an out-of-range value.

---

## 19. Glossary

**Aeroponics** — growing method in which the roots hang in air and are misted at intervals
with a solution of water and nutrients.

**Hydroponics** — soil-free growing in which the roots are in contact with a nutrient
solution.

**Nutrient solution** — the water with the salts that feed the plants dissolved in it.

**pH** — how acidic the water is. Scale from 0 to 14, 7 is neutral. If it is wrong, the plants
cannot take up nutrients even though they are there. Typical desired value: 5.5–6.5.

**EC (electrical conductivity)** — how concentrated the solution is in nutrient salts, deduced
from how well it conducts electricity. Measured in µS/cm (microsiemens per centimetre).

**TDS** — the same salts as EC, expressed in ppm (parts per million, i.e. milligrams per
litre). The same information in a different unit.

**Salinity** — how salty the solution is, in PSU. Also derived from the EC measurement.

**VPD** — "how thirsty the air is": the pull the air exerts on the leaves to make them
transpire. It combines temperature and humidity in a single number.

**MCARI2** — a number between 0 and 1 summarising the health of the plants, derived from the
colour of the light the leaves reflect.

**Job** — an automatic, repeated switch-on of a device (typically a pump), defined by an
interval and a duration.

**Ultrasound** — the principle behind the two distance meters: they emit a sound too
high-pitched to be heard and time how long the echo takes to come back. The later the echo,
the farther the object.

**Calibration** — teaching an instrument what the right value is in a known situation, so that
from then on it can measure all the others correctly.

**Arduino board** — the "probe box": the device connected by USB to which the pH and EC probes
and the two distance meters are attached.

**Log** — the program's diary, i.e. the time-ordered list of everything it has done.
