import { ref, watch, onUnmounted, type Ref } from 'vue';

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
    const el = containerRef.value;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }

  let attached: HTMLElement | null = null;
  let observer: MutationObserver | null = null;

  function detach() {
    if (attached) attached.removeEventListener('scroll', check);
    if (observer) observer.disconnect();
    attached = null;
    observer = null;
  }

  function attach(el: HTMLElement) {
    el.addEventListener('scroll', check, { passive: true });
    observer = new MutationObserver(() => {
      if (isNearBottom.value) scrollToBottom();
    });
    // `characterData: true` is required because streaming token updates
    // often mutate existing text nodes rather than insert children.
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    attached = el;
  }

  watch(
    containerRef,
    (el) => {
      detach();
      if (el) attach(el);
    },
    { immediate: true, flush: 'post' },
  );

  onUnmounted(detach);

  return { containerRef, isNearBottom, showScrollButton, scrollToBottom };
}
