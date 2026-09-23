-- hr-fullwidth.lua
-- Makes markdown horizontal rules (---) span the full text width,
-- matching the body text margins instead of pandoc's default
-- centered half-width rule.

function HorizontalRule(elem)
  return pandoc.RawBlock('latex', '\\noindent\\rule{\\linewidth}{0.15pt}')
end