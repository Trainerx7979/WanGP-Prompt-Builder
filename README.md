# WanGP-Prompt-Builder
A python app that allows you to edit prompts for WanGP alongside an audio track in a 'video editor' style layout. Includes Ollama integration for local prompt generation, and has a Fill Timeline function with random or set duration prompts that Ollama can auto-fill based on your Project description.

<img width="1399" height="832" alt="wpg2" src="https://github.com/user-attachments/assets/52fd44b9-35f3-47e9-a66a-5a5a23609e8f" />


**Why is this a thing?**

Scenario: You have a song you want to make a music video for. Or a quick teaser video you want to make.
You have your idea, you know the song length. You have WanGP2 to generate clips that will end up being
your full video. 

**What this tool will do**

You can enter your idea, load your song, generate random or set-time blocks of prompts to fill the video.
Adjust them to match the intensity of the music/timing of lyrics/etc. Visually move them and play that
section to see how the timing lines up in real time.

Send empty prompt blocks to Ollama (with the Story or ide for your video [optional])
and Ollama will fill each of the prompts and negative blocks for each section.

Set up global prompts so that they "decorate" the standard prompt with overarching thematic or style guidelines

Export a json list of all the full prompts including global decorator prompts, with all details for each segment:
length, positive/negative prompts, start/end time...

**What this tool WILL do soon**

The end goal is for this tool to also handle taking the last image of the last generation, and automatically
using that as the starting image for the next prompt block.

Automatically handle sending Json to Wan2GP, initiate the video generation process, collect video and first/last frames,
Retrieve final clips and compile into finished video.
