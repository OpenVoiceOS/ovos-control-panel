# Mark-1 faceplate

The Mark-1 faceplate page controls the eyes and the mouth of a Mark-1
device. You draw an image for the mouth. You set the eyes, either a whole ring at a
time or one LED at a time. You can preview the result in the browser before
you send it, and mirror what the device is showing.

![The Mark-1 faceplate page](img/mark1-wide.png)

![The same page on a phone](img/mark1-mobile.png)

## What it needs

Sending anything to real hardware needs the `ovos-PHAL-plugin-mk1` plugin.
Install it on the device first. Without the plugin the page still works: the
simulator and the mouth editor run in the browser, and the controls still put
their messages on the bus, where nothing picks them up.

The page tries to confirm a Mark-1 by asking the faceplate two things: what
colour the eyes are showing, and what firmware it runs. Either answer is proof
enough. A plugin that answers neither leaves the page unable to tell a working
device from an absent one, so it says it could not confirm a Mark-1 and
disables nothing on that basis. Mirroring the live face and the firmware card
do need a confirmed device, because both read from it.

## The face

The canvas at the top of the page is laid out the way the hardware is: the
left eye, the mouth, and the right eye in a row, behind one panel.

Each eye is a ring of twelve individually addressable colour LEDs, and the
mouth is a grid of 32 by 8 white ones. The page draws every one of them
separately, so what you see is the arrangement the device actually has rather
than a sketch of a face.

Click a single LED in either ring to light it in the colour you have picked.
Click it again, with the same colour still chosen, to turn it off. With a
device connected the change goes straight to that one LED. The colour control
above changes the whole ring at once.

Where the device answers the eye-colour question, the page reads it and
follows it. The eyes show what the device is showing, including changes
something else made — a skill lighting them up, or the volume knob. Press
**Stop following** to keep the face as your own design instead; press **Follow
the device** to go back.

Otherwise the canvas is a simulator. It runs entirely in the browser,
so you can design a faceplate before you own a Mark-1, or before you set up
the plugin.

## Build an animation

Set the face the way you want it, then press **Add this face as a frame**. Do
it again for the next pose. Each frame holds the mouth drawing and all
twenty-four eye LEDs, so a frame that changes only the eyes is a real frame.

The strip below shows every frame as a thumbnail. The number loads that frame
back onto the face; the × removes it.

**Play here** runs the sequence in the browser. **Play on the device** sends
each frame to a real Mark-1 in turn.

Frames are held for the time in **Hold each frame**, and that will not go
below 0.4 seconds. That is the floor `ovos-mark1-utils` clamps an animation
to, because the faceplate misbehaves when it is written to faster. The board takes
its commands over a slow serial link, so a frame that changes many LEDs is held
longer than the floor, for about as long as its own writes take to reach the
board. Only the LEDs that changed are sent, so a frame that moves the mouth and
leaves the eyes alone runs at the floor.

### Export

**Export animation** writes a JSON file, which **Import animation** reads back.
That is the format to share with another Mark-1 owner.

**Export as Python** writes a `FacePlateAnimation` subclass instead — the same
shape `ovos-mark1-utils` uses — so an animation designed here can be dropped
into a skill and run from code. The exported file carries the frame delay you
chose.

## Faceplate firmware

The eyes and the mouth are driven by a small board with its own firmware,
separate from the OVOS software on the device. It rarely needs changing.

The page shows which version the board reports and whether a newer one is
available. When the board has not reported a version yet the page says so,
rather than treating silence as an old version.

Updating rewrites that board. It is built on the device first, because there
is no prebuilt firmware to download any more, so the whole operation takes a
few minutes. **Do not power the device off while it runs.** If the write is
interrupted the eyes and the mouth stop working until the update is run again.
The page asks you to type `UPDATE` before it starts, and reports success only
once the board reports its new version — not merely once the request was
accepted.

Managing firmware needs a version of `ovos-PHAL-plugin-mk1` that supports it.
Where the plugin is older, the page says so instead of offering an update.

## Draw the mouth

The mouth display is 8 rows by 32 columns of pixels. Click or drag on the
grid to turn pixels on and off.

Use **Clear** to start over, or **Invert** to swap every pixel. Three
presets load a ready-made image: **Heart**, **Music note**, and
**Smile**. Press **Send drawing to device** to show your drawing on a
connected Mark-1.

## Mouth text and animations

Type text in the **Scrolling text** field and press **Scroll text** to
show it, letter by letter, on the mouth. **Reset mouth** clears the
display. The viseme buttons (0 to 6) and the animation buttons (**Talk**,
**Think**, **Listen**, **Smile**) play the mouth's built-in shapes.

## The eyes

Pick a color with the color picker. It also updates the simulator at
once. **On** and **Off** turn the eyes on or off. **Blink** closes one
eye or both for a moment. **Look** points the eyes in a direction.
**Narrow** and **Spin** play the eyes' built-in animations.

The **Brightness** slider sets how bright the eyes glow, from 1 to 30.
The **Fill** slider sets how much of each eye is lit, from 0 to 100%.

## System

**Reset** puts the whole faceplate back to its startup state. **Mute**
and **Unmute** silence or restore the enclosure's own sounds. **Blink**
makes the enclosure blink a few times, as a visible "I heard that"
signal.

## How it talks to the device

Every eye, mouth and system control sends one of the Mark-1's own
`enclosure.*` bus messages, the same ones `ovos-PHAL-plugin-mk1` already
listens for. For those the page is a browser front end for controls the plugin
has always had. The firmware card is the exception: it uses
`enclosure.firmware.version.get` and `enclosure.firmware.update`, which the
plugin answers only where firmware support is present.

## If it doesn't work

If the page says it could not confirm a Mark-1, the controls still send. The
page asks the faceplate two questions, and only a version of
`ovos-PHAL-plugin-mk1` that answers one of them will reply, so a working device
can stay silent. Where the plugin is missing altogether, install it from the
[Plugins](plugins.md) page and reload.

A control reports only that the message reached the bus. Nothing on the bus
says whether the faceplate acted on it, so a control that reports success on a
device with no plugin running is telling the truth about what it can see. Where
the eyes or the mouth do not change, check that the plugin is running and read
its log. For anything else, see [troubleshooting.md](troubleshooting.md).

---
[← Servers](servers.md) · [Home](README.md) · [Wallpaper →](wallpaper.md)
