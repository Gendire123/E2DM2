# Easy Epic Drone Movie Maker (E2DM2)

> Drone filmmaking, simplified. From flight to epic.

E2DM2 is a local Windows desktop application that transforms drone footage into polished, music-synchronized movies without requiring a traditional video-editing workflow.

## Latest Release: E2DM2 v1.1.0

Download the Windows installer from the v1.1.0 release assets:

**[Download E2DM2-Setup-1.1.0.exe](https://github.com/Gendire123/E2DM2-Releases/releases/download/v1.1.0/E2DM2-Setup-1.1.0.exe)**

Version 1.1.0 introduces verified digital code signing backed by Microsoft Azure Trusted Signing:

- **Verified Identity & Code Integrity:** Both the standalone application executable (`E2DM2.exe`) and the setup installer (`E2DM2-Setup-1.1.0.exe`) are digitally signed using Microsoft's cloud identity verification service.
- **Windows SmartScreen Integration:** Provides a smooth, trusted installation experience on Windows 10 and Windows 11 without unverified publisher warnings.

See the [v1.1.0 release page](https://github.com/Gendire123/E2DM2-Releases/releases/tag/v1.1.0) for the complete release notes, installer asset, file size, and publication details.

## Installation and Upgrade

1. Download `E2DM2-Setup-1.1.0.exe` from the v1.1.0 release assets.
2. Double-click the installer and follow the on-screen instructions.
3. If an earlier version is installed, the setup process replaces the application while leaving projects and user-created media available.
4. Start E2DM2 and open **Help > About E2DM2** to verify that version 1.1.0 is installed.

Windows SmartScreen may warn about a new independent publisher. Confirm that the installer came from the official E2DM2 Releases repository and compare any published checksum before continuing.

## System Requirements

- **Operating system:** Windows 10 or Windows 11, 64-bit
- **Memory:** 8 GB RAM minimum
- **Graphics:** NVIDIA or AMD dedicated GPU recommended for faster rendering
- **Storage:** Enough free space for source footage, temporary previews, rendered movies, and the application package

## Privacy and Local Processing

E2DM2 performs video and audio processing locally on the user's computer. Imported footage, custom soundtracks, generated previews, project data, and rendered movies are not uploaded for cloud processing.

The application uses limited internet connections for:

- automatic or user-requested update checks through GitHub; and
- optional Pro license activation and deactivation through the E2DM2 licensing service hosted by Supabase.

Purchases and contact requests open external pages in the user's browser. The complete policy is available inside E2DM2 under **Help > Privacy Policy**.

## Core Features

### Three-step workflow

1. **Import footage:** Add individual files, entire folders, or drag drone videos into the workspace.
2. **Select a soundtrack:** Choose a soundtrack and editing workflow to establish the movie's pacing and target duration.
3. **Produce the movie:** Render a polished montage whose cuts and effects follow the selected music.

### Selection Mode

Selection Mode adds direct creative control without requiring a full timeline editor:

- **Required:** Mark moments the final movie must preserve.
- **Exclude:** Mark ranges that must not appear in the final movie.
- **Preview and edit:** Review clips using fast local preview files and adjust selections visually.

E2DM2 combines these instructions with its montage planner to preserve required material and avoid excluded ranges while maintaining the selected soundtrack structure.

### Local project workflow

- Source footage remains in its original location.
- Project settings and recent-project information remain on the local computer.
- Preview proxies, thumbnails, waveform caches, logs, and renders are generated locally.
- Existing projects remain compatible with the onboarding and privacy-interface improvements in version 1.0.8.

## E2DM2 Pro

The standard application includes built-in soundtrack workflows. An optional Pro license unlocks additional creative controls:

- import custom soundtracks such as MP3, WAV, AAC, FLAC, and M4A files;
- create and edit custom timing cuts and effect presets; and
- export at full source resolution, including supported 4K footage.

Pro activation uses a license code and a randomly generated installation identifier. It does not upload project media or use a hardware serial number.

## Support and Information

Use **Help > Contact & Info** inside E2DM2 or visit [e2dm2.com](https://e2dm2.com/) for support, feature questions, and general information.

For privacy questions, open **Help > Privacy Policy** and follow the instructions in its **Contact and complaints** section.

## About E2DM2

> "I wanted the finished movie to feel as exciting as the flight itself."

E2DM2 was created by Felix Ouellet to make high-quality drone movie creation faster and more approachable for pilots who want polished results without spending hours in a conventional editor.

Copyright 2026 E2DM2. All rights reserved.
