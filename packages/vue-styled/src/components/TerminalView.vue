<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';

const props = defineProps<{
  onData?: (data: Uint8Array) => void;
  onResize?: (cols: number, rows: number) => void;
  fontSize?: number;
}>();

const containerRef = ref<HTMLElement | null>(null);
let terminal: Terminal | null = null;
let fitAddon: FitAddon | null = null;
let resizeObserver: ResizeObserver | null = null;

function writeData(data: Uint8Array) {
  terminal?.write(data);
}

defineExpose({ writeData });

onMounted(() => {
  if (!containerRef.value) return;
  terminal = new Terminal({
    fontSize: props.fontSize ?? 14,
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    theme: {
      background: '#1e1e2e',
      foreground: '#cdd6f4',
      cursor: '#f5e0dc',
    },
    cursorBlink: true,
  });
  fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(containerRef.value);
  fitAddon.fit();

  terminal.onData((data) => {
    const encoded = new TextEncoder().encode(data);
    props.onData?.(encoded);
  });

  terminal.onResize(({ cols, rows }) => {
    props.onResize?.(cols, rows);
  });

  resizeObserver = new ResizeObserver(() => {
    fitAddon?.fit();
  });
  resizeObserver.observe(containerRef.value);
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  terminal?.dispose();
});
</script>

<template>
  <div ref="containerRef" class="aia-terminal-view" />
</template>

<style scoped>
.aia-terminal-view {
  width: 100%;
  height: 100%;
  min-height: 300px;
  background: #1e1e2e;
  border-radius: var(--aia-radius-md, 8px);
  overflow: hidden;
}
</style>
