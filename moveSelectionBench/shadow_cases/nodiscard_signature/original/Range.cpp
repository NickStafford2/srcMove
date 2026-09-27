class Range {
public:
    bool Contains(Sci::Position pos) const noexcept {
        if (start < end) {
            return pos >= start && pos <= end;
        } else {
            return pos <= start && pos >= end;
        }
    }

private:
    Sci::Position start;
    Sci::Position end;
};
