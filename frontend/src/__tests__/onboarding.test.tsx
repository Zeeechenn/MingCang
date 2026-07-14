import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));

vi.mock('../shared', () => ({
  Badge: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  navigate,
}));

import {
  FirstRunWizard,
  ONBOARDING_GOAL_KEY,
  TOUR_STEPS,
  WIZ_KEY,
} from '../onboarding';

describe('first-run onboarding', () => {
  beforeEach(() => {
    localStorage.clear();
    navigate.mockClear();
  });

  it('is a short accessible dialog and persists the selected starting goal', () => {
    const onDone = vi.fn();
    const onStartTour = vi.fn();
    render(<FirstRunWizard onDone={onDone} onStartTour={onStartTour} />);

    expect(screen.getByRole('dialog', { name: '欢迎使用明仓' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /复盘/ }));
    fireEvent.click(screen.getByRole('button', { name: '继续' }));
    fireEvent.click(screen.getByRole('button', { name: '继续' }));
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '完成并进入' }));

    expect(localStorage.getItem(WIZ_KEY)).toBe('1');
    expect(localStorage.getItem(ONBOARDING_GOAL_KEY)).toBe('review');
    expect(navigate).toHaveBeenCalledWith('/reports');
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onStartTour).not.toHaveBeenCalled();
  });

  it('documents every top-level navigation destination in the tour', () => {
    expect(TOUR_STEPS.map((step) => step.route)).toEqual([
      '/',
      '/daily',
      '/pulse',
      '/stocks',
      '/reports',
      '/chat',
      '/positions',
      '/memory-evolution',
      '/health',
      '/admin',
    ]);
  });
});
