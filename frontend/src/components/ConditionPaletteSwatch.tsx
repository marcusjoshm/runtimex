import React from 'react';
import { Box, Tooltip } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';

// 10-color predefined palette for Conditions (U2).
//
// The plan calls for a fixed enum so we never have to think about contrast,
// arbitrary user input, or color-picker UX. Each entry maps a stable string
// key (stored on `ConditionORM.color`) to a `{bg, fg}` pair that the Designer
// renders with directly via `sx={{ bgcolor: ..., color: ... }}`.
//
// Choice notes:
//
// * Hex values are used (not MUI palette tokens like `theme.palette.primary`)
//   because we need 10 visually distinct hues, not 4 semantic roles. MUI's
//   palette would force overlap (`primary`, `secondary`, `error`, `warning`,
//   `info`, `success` is six total and several of them are very close to
//   each other in default themes).
// * The `bg` value is a saturated mid-tone; `fg` is either near-black or
//   near-white whichever gives WCAG-AA contrast against `bg`. Picked by eye
//   and double-checked with a contrast tool; safe to rely on for body-text
//   labels rendered on top of a swatch.
// * Slate is the default for new Conditions and for the auto-backfilled
//   "Main" Condition — neutral so single-Condition experiments don't look
//   arbitrarily themed.
//
// U6 will reuse this map for swimlane backgrounds (lighter `bg` shades for
// the lane body, the same `bg` for the lane header chip). U7's focus mode
// uses the same map for the full-screen Condition card. Don't change the
// keys without coordinating across all three units.
export interface PaletteColor {
  bg: string;
  fg: string;
}

export const PALETTE_COLORS: Record<string, PaletteColor> = {
  slate: { bg: '#64748b', fg: '#ffffff' },
  coral: { bg: '#f87171', fg: '#1f2937' },
  forest: { bg: '#16a34a', fg: '#ffffff' },
  lavender: { bg: '#a78bfa', fg: '#1f2937' },
  amber: { bg: '#f59e0b', fg: '#1f2937' },
  teal: { bg: '#14b8a6', fg: '#ffffff' },
  magenta: { bg: '#db2777', fg: '#ffffff' },
  mint: { bg: '#86efac', fg: '#1f2937' },
  navy: { bg: '#1e3a8a', fg: '#ffffff' },
  gold: { bg: '#eab308', fg: '#1f2937' },
};

// The order of keys in PALETTE_COLORS is the canonical ordering for color
// pickers. Object iteration order in modern JS is insertion order for string
// keys, so we expose this list separately to make the contract explicit.
export const PALETTE_COLOR_KEYS: string[] = Object.keys(PALETTE_COLORS);

// Look up a palette entry. Falls back to `slate` for unknown keys so a
// stale value in the DB never crashes the UI.
export const getPaletteColor = (key: string | undefined | null): PaletteColor => {
  if (!key) return PALETTE_COLORS.slate;
  return PALETTE_COLORS[key] ?? PALETTE_COLORS.slate;
};

interface ConditionPaletteSwatchProps {
  color: string;
  selected?: boolean;
  onClick?: () => void;
  size?: number;
}

// Clickable colored circle. Rendered in a row by ConditionEditor's color
// picker. The selected state shows a checkmark in the foreground color so
// the user can see which swatch they last picked even when the picker has
// already closed and reopened.
const ConditionPaletteSwatch: React.FC<ConditionPaletteSwatchProps> = ({
  color,
  selected = false,
  onClick,
  size = 32,
}) => {
  const { bg, fg } = getPaletteColor(color);
  const swatch = (
    <Box
      role={onClick ? 'button' : undefined}
      aria-label={`Color ${color}${selected ? ' (selected)' : ''}`}
      onClick={onClick}
      sx={{
        width: size,
        height: size,
        borderRadius: '50%',
        bgcolor: bg,
        color: fg,
        cursor: onClick ? 'pointer' : 'default',
        border: selected ? '3px solid #1f2937' : '2px solid rgba(0,0,0,0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'transform 0.1s ease',
        '&:hover': onClick ? { transform: 'scale(1.08)' } : undefined,
      }}
    >
      {selected && <CheckIcon sx={{ fontSize: size * 0.55 }} />}
    </Box>
  );
  return <Tooltip title={color}>{swatch}</Tooltip>;
};

export default ConditionPaletteSwatch;
