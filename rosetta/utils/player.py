from pomice import Filter, Player, Queue

class CustomPlayer(Player):
    def __init__(self, client, channel, *, node = None):
        super().__init__(client, channel, node=node)
        self.queue = Queue()

class NormalizeFilter(Filter):
    def __init__(self):
        super().__init__(tag="normalizer")

        self.payload = {
            "pluginFilters": {
                "normalization": { # Attenuates peaking where peaks are defined as having a higher value than {maxAmplitude}. 
                    "maxAmplitude": 0.07, # Float, within the range of 0.0 - 1.0. A value of 0.0 mutes the output.
                    "adaptive": True    # Boolean, whether peak amplitudes should persist. Refer to the note below for more information.
                }
            }
        }