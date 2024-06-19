import { reactive, ref, onMounted } from "vue";
import { DiscordSDK } from "@discord/embedded-app-sdk";

interface Auth {
  access_token: string;
  user: {
    username: string;
    discriminator: string;
    id: string;
    public_flags: number;
    avatar?: string | null | undefined;
    global_name?: string | null | undefined;
  };
  scopes: (
    | -1
    | "identify"
    | "email"
    | "connections"
    | "guilds"
    | "guilds.join"
    | "guilds.members.read"
    | "gdm.join"
    | "rpc"
    | "rpc.notifications.read"
    | "rpc.voice.read"
    | "rpc.voice.write"
    | "rpc.video.read"
    | "rpc.video.write"
    | "rpc.screenshare.read"
    | "rpc.screenshare.write"
    | "rpc.activities.write"
    | "bot"
    | "webhook.incoming"
    | "messages.read"
    | "applications.builds.upload"
    | "applications.builds.read"
    | "applications.commands"
    | "applications.commands.update"
    | "applications.commands.permissions.update"
    | "applications.store.update"
    | "applications.entitlements"
    | "activities.read"
    | "activities.write"
    | "relationships.read"
    | "voice"
    | "dm_channels.read"
    | "role_connections.write"
  )[];
  expires: string;
  application: {
    id: string;
    description: string;
    name: string;
    icon?: string | null | undefined;
    rpc_origins?: string[] | undefined;
  };
}

export const useDiscordSdk = () => {
  const auth = ref<Auth | null>(null);
  const isReady = ref(false);
  const discordSdk = reactive(
    new DiscordSDK(import.meta.env.VITE_DISCORD_CLIENT_ID)
  );

  async function setupDiscordSdk() {
    await discordSdk.ready();

    const { code } = await discordSdk.commands.authorize({
      client_id: import.meta.env.VITE_DISCORD_CLIENT_ID,
      response_type: "code",
      state: "",
      prompt: "none",
      scope: ["identify", "guilds", "rpc.activities.write"],
    });

    // Retrieve an access_token from your activity's server
    const response = await fetch("/api/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        code,
      }),
    });
    const { access_token } = await response.json();

    // Authenticate with Discord client (using the access_token)
    auth.value = await discordSdk.commands.authenticate({
      access_token,
    });

    if (auth.value == null) {
      throw new Error("Authenticate command failed");
    }
  }

  onMounted(() => {
    setupDiscordSdk().finally(() => {
      isReady.value = true;
    });
  });

  return {
    auth,
    isReady,
    discordSdk,
  };
};

export default useDiscordSdk;
