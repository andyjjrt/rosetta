#!/bin/bash

# Define an array
my_array=(
  "https://youtu.be/WOrYBIYIwyk::1-3"
  "https://youtu.be/ijdspfPMzYc::4"
  "https://youtu.be/zfA0zRAkAdk::5"
  "https://youtu.be/UwgyEoB9vU8::6"
  "https://youtu.be/rlY2b3TIYPs::7"
  "https://youtu.be/mfboDpl88QY::8"
  "https://youtu.be/ySjYENzyZmY::9"
  "https://youtu.be/bLWDIYpGcEI::10"
  "https://youtu.be/gAFDVnhX24o::11"
  "https://youtu.be/wei3payuSi8::12"
  "https://youtu.be/uQ3_PvPCNnI::13"
  "https://youtu.be/dxmmSFQxWzM::ave-1"
  "https://youtu.be/Bzl61esi4qc::ave-2"
  "https://youtu.be/HagaJboujK4::ave-3"
  "https://youtu.be/Z6cOxtDsfNU::ave-4"
  "https://youtu.be/7D2uGv7aprQ::ave-5"
  "https://youtu.be/jQraN1emvLQ::ave-6"
  "https://youtu.be/RONGNWb7OpQ::ave-7"
  "https://youtu.be/uh9jUhVTS28::ave-8"
  "https://youtu.be/pGrI6hk0vBg::ave-9"
  "https://youtu.be/m9cjOcCKIyQ::ave-10"
  "https://youtu.be/Cfm8TWGkvYQ::ave-11"
  "https://youtu.be/UtSEFdDZZLw::ave-12"
)

# Update the loop sections:
echo "Looping through array elements:"
for item in "${my_array[@]}"; do
  url=${item%%::*}
  episode=${item##*::}
  echo "Processing: URL=$url, Episode=$episode"
  $(which yt-dlp) $url -S res,ext:mp4:m4a --recode mp4  -o "$episode.%(ext)s"
done

wget https://raw.githubusercontent.com/Its-MyPic/Its-MyPicDB/refs/heads/json/data.json