import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
  Stack,
} from '@mui/material';
import { Condition } from '../api/client';
import ConditionPaletteSwatch, { PALETTE_COLOR_KEYS } from './ConditionPaletteSwatch';

interface ConditionEditorProps {
  // The Condition being edited. Pass a freshly-built Condition for "create new",
  // or an existing one (from `experiment.conditions`) for "edit". The editor
  // copies the value into local state so an in-flight edit can be cancelled
  // without mutating the caller's source of truth.
  condition: Condition;
  // True when the dialog is open. Closing the dialog without saving fires
  // `onCancel`; saving fires `onSave` with the edited Condition.
  open: boolean;
  onSave: (condition: Condition) => void;
  onCancel: () => void;
  // Title hint -- "Edit Condition" vs "Add Condition". Defaults to "Edit"
  // so the most-common path doesn't need to pass it.
  title?: string;
}

// Modal editor for one Condition (U2).
//
// Design choice: a Dialog (rather than an inline panel or a Drawer) -- the
// Designer page already uses dialogs for Step editing, so users have a
// consistent "edit this thing in place" mental model. The dialog is small
// and one-shot; a Drawer would be overkill for three fields.
//
// The save button is disabled when the name is empty so we can't produce a
// nameless Condition. Color defaults to whatever was already set on the
// Condition (slate for new ones); description is optional.
const ConditionEditor: React.FC<ConditionEditorProps> = ({
  condition,
  open,
  onSave,
  onCancel,
  title = 'Edit Condition',
}) => {
  // Local copy so cancel really cancels. Reset whenever the editor opens on
  // a new Condition (the parent passes a freshly-built dataclass for "add",
  // an existing one for "edit"; either way we want the form to mirror the
  // input on each open).
  const [draft, setDraft] = useState<Condition>(condition);

  useEffect(() => {
    if (open) {
      setDraft(condition);
    }
  }, [condition, open]);

  const handleSave = () => {
    if (!draft.name.trim()) return;
    onSave({ ...draft, name: draft.name.trim() });
  };

  return (
    <Dialog open={open} onClose={onCancel} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          <TextField
            fullWidth
            label="Condition Name"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
            autoFocus
          />
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              Color
            </Typography>
            <Box
              sx={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 1.5,
                mt: 1,
              }}
            >
              {PALETTE_COLOR_KEYS.map((colorKey) => (
                <ConditionPaletteSwatch
                  key={colorKey}
                  color={colorKey}
                  selected={draft.color === colorKey}
                  onClick={() => setDraft({ ...draft, color: colorKey })}
                />
              ))}
            </Box>
          </Box>
          <TextField
            fullWidth
            label="Description"
            value={draft.description ?? ''}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            multiline
            rows={2}
            placeholder="Optional notes about this condition (e.g., 'Dish 1 — control')"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button onClick={handleSave} variant="contained" disabled={!draft.name.trim()}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ConditionEditor;
