export const EXAMPLE_QUESTION =
  'Who has had 40 home runs and 40 stolen bases in the same year?';

export const CLARIFICATION_QUESTION = 'Who had the most strikeouts in 2024?';

export const RECIPE = [
  { label: 'Who', value: 'Players' },
  { label: 'Grain', value: 'Same season' },
  { label: 'Condition', value: 'HR ≥ 40' },
  { label: 'Condition', value: 'SB ≥ 40' },
];

export const RESULTS = [
  { player: 'José Canseco', year: 1988, hr: 42, sb: 40 },
  { player: 'Barry Bonds', year: 1996, hr: 42, sb: 40 },
  { player: 'Alex Rodriguez', year: 1998, hr: 42, sb: 46 },
  { player: 'Alfonso Soriano', year: 2006, hr: 46, sb: 41 },
  { player: 'Ronald Acuña Jr.', year: 2023, hr: 41, sb: 73 },
  { player: 'Shohei Ohtani', year: 2024, hr: 54, sb: 59 },
];

export const FIELD_GROUPS = [
  { name: 'Identity', fields: ['Player', 'Team', 'League'] },
  { name: 'Time', fields: ['Season', 'Stint'] },
  { name: 'Batting', fields: ['HR', 'SB', 'AB', 'R', 'H', 'RBI'] },
];
