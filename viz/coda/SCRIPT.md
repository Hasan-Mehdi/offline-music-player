# How Coda works: the script

The narration as it appears in the film (on-screen text, in Hasan's voice). Numbers in
${...} are filled in from the data at build time. The source of truth is `script()` in `coda.html`.

## 1. How it picks songs

> This is a HiFi Walker H2. It’s a $124 MP3 player, and it runs a music app I made called Coda.
>
> It has 18,000 of my songs on it, and when one ends, Coda picks the next one.

> An AI model on my PC listened to every song and turned each one into 512 numbers that describe how it sounds.
>
> Songs that sound alike get similar numbers.

> To choose what’s next, Coda takes the few hundred songs that sound closest to what’s playing.
>
> Each one gets a score: how close it sounds, how well it fits my taste, whether I’ve heard it lately, and whether it’s the same artist again.
>
> The highest score plays. About one pick in five tries something a little different on purpose.

> My taste comes from my YouTube Music history: almost 11,000 listens.

> There was a problem, though. Every fingerprint leaned in the same direction, so to Coda, all songs looked somewhat alike.
>
> My taste ended up being basically the average song.
>
> Subtracting that shared lean from every song fixed it.

> To test it, I hid the 410 songs I got into after late July and had it pick between one of those and a random song.
>
> It used to get that right 54% of the time, barely better than a coin flip. Now it’s 67%.

## 2. Why this player

> I wanted a separate music player with real buttons that fits in my pocket.
>
> Game Boy-style handhelds looked like Game Boys, and building my own meant soldering and designing a case.

> The H2 works because of Rockbox. It’s free, open-source software for music players that people have worked on for over twenty years.
>
> It replaces the software a player ships with, and all of its code is public, so you can change any part of it.
>
> The H2 is about the only player still being made that Rockbox runs on.

## 3. What’s inside

> Inside there’s a 1 GHz processor with 32 megabytes of memory, a chip that turns the music into a signal for headphones, a Bluetooth chip, a battery, and a memory card with the songs.

> When you turn it on, a tiny program called the bootloader runs first. It looks on the card for a folder called .rockbox and starts whatever is in it.
>
> So changing the whole system means copying a different folder onto the card.

## 4. Rewriting it in C

> Coda started as a website. It ran in a browser, with a Python program on my PC choosing the songs.
>
> The H2 has no browser and no Python, and a phone has about 250 times more memory.

> So Coda was rewritten in C, which turns into instructions for this exact processor with nothing in between. It’s over ${fmtInt(lines)} lines.

> It’s built in layers. The brain picks songs. The UI draws every pixel. Under those is a thin layer that’s the only part allowed to touch the hardware.
>
> That bottom layer has two versions: one for the player, and one for my PC that saves every frame as a picture, so each screen could be checked before it went on the device.

> Decimal math is slow on this chip, so all the drawing uses whole numbers.
>
> Rockbox apps only get 2 megabytes of memory, so the library stays on the card and gets read a piece at a time.

> Anything heavy happens once, on my PC: shrinking the cover art, evening out the loudness, and packing every song’s data into files the player only has to read.

> To check that the C brain matches the Python one, both get the same ${D.engine3.cases} situations. They pick the same song all ${D.engine3.match} times.

## 5. Coda OS

> At first, Coda was an app inside Rockbox. You’d land in Rockbox’s menus and go to Plugins, then Applications, then Coda, and it only had 2 megabytes.

> Rockbox is built in layers too. At the bottom are the drivers for the chips, including battery charging. Then the codecs, which unpack music files into sound. Then playback, and the menus on top.

> Coda OS is my own build of Rockbox with Coda built in. The drivers, codecs and playback stay Rockbox’s, because charging a lithium battery wrong is dangerous.
>
> The menus get hidden, and Coda takes their place with 8 megabytes instead of 2.

> Now the player starts straight into Coda.
>
> The old menus are still there if you hold Menu and Back.

## 6. Themes

> Every screen is drawn by Coda’s own code. New looks start as mockups made with my real songs, at the player’s exact size.
>
> A new menu and a batch of pixel-art themes are next.

## 7. Bluetooth

> The H2 has a Bluetooth chip, but Rockbox never supported it. Skye Green, from the Rockbox community, had started a port. It could connect to headphones, but any error crashed the player.

> Making it solid meant fixing about a dozen bugs. Messages over 255 bytes got their length cut off. Two messages could get mixed together on the wire. The volume was stuck at full.

> On the first real test, my Galaxy Buds connected, but there was no sound. The player never set the Bluetooth volume, so every sample was multiplied by zero.
>
> That’s fixed, and waiting on the next test.

## 8. What’s next

> The 64 GB card holds 18,000 songs. All ${lib},000 would fit on a 256 GB card.
>
> Plays sync back to my PC when I plug it in, so it keeps learning.
>
> And since only the bottom layer of Coda touches hardware, the same app could move to a player I build myself.
