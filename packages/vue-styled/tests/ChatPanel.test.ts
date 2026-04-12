import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import ChatPanel from '../src/components/ChatPanel.vue';

describe('ChatPanel', () => {
  const messages = [
    { id: 'm1', role: 'user' as const, content: 'Hello', model: null, tokens_in: null, tokens_out: null },
    { id: 'm2', role: 'assistant' as const, content: 'Hi there!', model: 'fake-1', tokens_in: 5, tokens_out: 3 },
  ];
  it('renders messages', () => {
    const w = mount(ChatPanel, { props: { messages } });
    expect(w.text()).toContain('Hello');
    expect(w.text()).toContain('Hi there!');
  });
  it('emits send on button click', async () => {
    const w = mount(ChatPanel, { props: { messages } });
    await w.find('textarea').setValue('New message');
    await w.find('button').trigger('click');
    expect(w.emitted('send')?.[0]).toEqual(['New message']);
  });
  it('shows streaming text', () => {
    const w = mount(ChatPanel, { props: { messages, isStreaming: true, streamingText: 'Generating...' } });
    expect(w.text()).toContain('Generating...');
  });
  it('disables input while streaming', () => {
    const w = mount(ChatPanel, { props: { messages, isStreaming: true } });
    expect(w.find('textarea').attributes('disabled')).toBeDefined();
  });
});
