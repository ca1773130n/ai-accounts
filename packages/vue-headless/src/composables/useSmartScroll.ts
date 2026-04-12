import { ref, onMounted, onUnmounted, type Ref } from 'vue';

export interface UseSmartScrollReturn {
  containerRef: Ref<HTMLElement | null>;
  isNearBottom: Ref<boolean>;
  showScrollButton: Ref<boolean>;
  scrollToBottom: () => void;
}

const THRESHOLD = 32;

export function useSmartScroll(): UseSmartScrollReturn {
  const containerRef = ref<HTMLElement | null>(null);
  const isNearBottom = ref(true);
  const showScrollButton = ref(false);

  function check() {
    const el = containerRef.value;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < THRESHOLD;
    isNearBottom.value = near;
    showScrollButton.value = !near;
  }

  function scrollToBottom() {
    containerRef.value?.scrollTo({ top: containerRef.value.scrollHeight, behavior: 'smooth' });
  }

  let observer: MutationObserver | null = null;

  onMounted(() => {
    const el = containerRef.value;
    if (!el) return;
    el.addEventListener('scroll', check, { passive: true });
    observer = new MutationObserver(() => {
      if (isNearBottom.value) scrollToBottom();
    });
    observer.observe(el, { childList: true, subtree: true });
  });

  onUnmounted(() => {
    containerRef.value?.removeEventListener('scroll', check);
    observer?.disconnect();
  });

  return { containerRef, isNearBottom, showScrollButton, scrollToBottom };
}
