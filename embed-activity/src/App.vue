<script setup lang="ts">
import { ref, onMounted, watch } from "vue";
import { useDiscordSdk } from "./hooks/useDiscordSdk";

const { isReady, auth, discordSdk } = useDiscordSdk();

watch(isReady, (val) => {
  if (val) {
    discordSdk.commands.setActivity({
      activity: {
        type: 2,
        details: "Details",
        state: "Playing",
      },
    });
  }
});
</script>

<template>
  <div>
    <a href="https://vitejs.dev" target="_blank">
      <img src="/vite.svg" class="logo" alt="Vite logo" />
    </a>
    <a href="https://vuejs.org/" target="_blank">
      <img src="./assets/vue.svg" class="logo vue" alt="Vue logo" />
    </a>
  </div>
  {{ isReady }}
  {{ auth }}
</template>

<style scoped>
.logo {
  height: 6em;
  padding: 1.5em;
  will-change: filter;
  transition: filter 300ms;
}
.logo:hover {
  filter: drop-shadow(0 0 2em #646cffaa);
}
.logo.vue:hover {
  filter: drop-shadow(0 0 2em #42b883aa);
}
</style>
