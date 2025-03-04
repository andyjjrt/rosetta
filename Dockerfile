FROM condaforge/miniforge3
COPY bot /app/bot
COPY environment.yml /app/environment.yml

WORKDIR /app
RUN mamba env create

VOLUME [ "/app/music" ]

ENTRYPOINT ["mamba", "run", "--no-capture-outpu", "-n", "rosetta", "python", "bot/bot.py"]