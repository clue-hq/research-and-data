//! Booklet imposition order math (print W4, D2) — pure and portable.
//!
//! Saddle-stitch booklets print 2-up on duplex sheets: fold the stack in
//! half, stitch the spine, and the pages must read in order. For N pages
//! (padded to a multiple of 4 with blanks), sheet `s` of N/4 carries
//! front `[N-2s | 1+2s]` and back `[2+2s | N-1-2s]` (1-based reader
//! numbers, left|right slots) — the classic printer's spread. N=4:
//! front [4|1], back [2|3].
//!
//! The back-side arrangement assumes the sheet turns about its VERTICAL
//! axis (left↔right swap, content upright) — for a landscape 2-up sheet
//! that is the "turn on short edge" duplex setting. This is declared in
//! the export diagnostics so the person at the printer knows.
//!
//! Deliberately NOT here (v2, only if shops demand): creep compensation,
//! multi-sheet signatures, work-and-turn, step-and-repeat ganging.

/// One side of one physical sheet: reader-page indices (0-based) for the
/// left and right slots; `None` is a padding blank.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BookletSheetSide {
    /// Sheet number, 0-based.
    pub sheet: usize,
    /// True for the front of the sheet, false for the back.
    pub front: bool,
    pub left: Option<usize>,
    pub right: Option<usize>,
}

/// Compute the duplex sheet-side sequence (front, back, front, back, …)
/// for `page_count` reader-order pages. Returns the sides and the number
/// of blank pages padded to reach a multiple of 4.
pub fn booklet_sheet_sides(page_count: usize) -> (Vec<BookletSheetSide>, usize) {
    if page_count == 0 {
        return (Vec::new(), 0);
    }
    let padding = (4 - page_count % 4) % 4;
    let total = page_count + padding;
    let sheets = total / 4;

    let index = |value: usize| -> Option<usize> { (value < page_count).then_some(value) };

    let mut sides = Vec::with_capacity(sheets * 2);
    for sheet in 0..sheets {
        sides.push(BookletSheetSide {
            sheet,
            front: true,
            left: index(total - 1 - 2 * sheet),
            right: index(2 * sheet),
        });
        sides.push(BookletSheetSide {
            sheet,
            front: false,
            left: index(2 * sheet + 1),
            right: index(total - 2 - 2 * sheet),
        });
    }
    (sides, padding)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pages(side: &BookletSheetSide) -> (Option<usize>, Option<usize>) {
        (side.left, side.right)
    }

    #[test]
    fn four_pages_is_the_classic_folded_sheet() {
        let (sides, padding) = booklet_sheet_sides(4);
        assert_eq!(padding, 0);
        assert_eq!(sides.len(), 2);
        // Front [4|1], back [2|3] in 1-based reader numbers.
        assert_eq!(pages(&sides[0]), (Some(3), Some(0)));
        assert_eq!(pages(&sides[1]), (Some(1), Some(2)));
        assert!(sides[0].front && !sides[1].front);
    }

    #[test]
    fn eight_pages_makes_two_sheets() {
        let (sides, padding) = booklet_sheet_sides(8);
        assert_eq!(padding, 0);
        assert_eq!(sides.len(), 4);
        assert_eq!(pages(&sides[0]), (Some(7), Some(0))); // [8|1]
        assert_eq!(pages(&sides[1]), (Some(1), Some(6))); // [2|7]
        assert_eq!(pages(&sides[2]), (Some(5), Some(2))); // [6|3]
        assert_eq!(pages(&sides[3]), (Some(3), Some(4))); // [4|5]
    }

    #[test]
    fn non_multiple_of_four_pads_with_trailing_blanks() {
        let (sides, padding) = booklet_sheet_sides(6);
        assert_eq!(padding, 2);
        assert_eq!(sides.len(), 4);
        // Padded total 8: blanks are reader indices 6 and 7 → None.
        assert_eq!(pages(&sides[0]), (None, Some(0))); // [blank|1]
        assert_eq!(pages(&sides[1]), (Some(1), None)); // [2|blank]
        assert_eq!(pages(&sides[2]), (Some(5), Some(2))); // [6|3]
        assert_eq!(pages(&sides[3]), (Some(3), Some(4))); // [4|5]
    }

    #[test]
    fn single_page_becomes_one_sheet_with_three_blanks() {
        let (sides, padding) = booklet_sheet_sides(1);
        assert_eq!(padding, 3);
        assert_eq!(sides.len(), 2);
        assert_eq!(pages(&sides[0]), (None, Some(0)));
        assert_eq!(pages(&sides[1]), (None, None));
    }

    #[test]
    fn every_reader_page_appears_exactly_once() {
        for count in [4usize, 8, 12, 6, 10, 5] {
            let (sides, _) = booklet_sheet_sides(count);
            let mut seen = vec![0usize; count];
            for side in &sides {
                for slot in [side.left, side.right].into_iter().flatten() {
                    seen[slot] += 1;
                }
            }
            assert!(seen.iter().all(|n| *n == 1), "count {count}: {seen:?}");
        }
    }
}
