from .meta import SnorkelBase, snorkel_postgres
from sqlalchemy import Table, Column, String, Integer, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.orm import relationship, backref
from sqlalchemy.types import PickleType


class CandidateSet(SnorkelBase):
    """A named collection of Candidate objects."""
    __tablename__ = 'candidate_set'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    def __repr__(self):
        return "Candidate Set (" + str(self.name) + ")"

    def append(self, item):
        self.candidates.append(item)

    def remove(self, item):
        self.candidates.remove(item)

    def __iter__(self):
        """Default iterator is over Candidate objects"""
        for candidate in self.candidates:
            yield candidate

    def __len__(self):
        return len(self.candidates)

    def __getitem__(self, key):
        return self.candidates[key]


class Candidate(SnorkelBase):
    """
    A candidate relation.
    """
    __tablename__ = 'candidate'
    id = Column(Integer, primary_key=True)
    candidate_set_id = Column(Integer, ForeignKey('candidate_set.id'))
    set = relationship('CandidateSet', backref=backref('candidates', cascade='all, delete-orphan'))
    type = Column(String, nullable=False)

    # Postgres requires an explicit unique index to use a tuple as a compound foreign key,
    # even if it is redundant as in this case
    if snorkel_postgres:
        __table_args__ = (
            Index('candidate_unique_id_candidate_set_id', id, candidate_set_id, unique=True),
        )

    __mapper_args__ = {
        'polymorphic_identity': 'candidate',
        'polymorphic_on': type
    }


class Ngram(Candidate):
    """
    A span of _n_ tokens, identified by Context id and character-index start, end (inclusive).

    char_offsets are **relative to the Context start**
    """
    __table__ = Table('ngram', SnorkelBase.metadata,
                      Column('id', Integer, unique=True),
                      Column('candidate_set_id', Integer, primary_key=True),
                      Column('context_id', Integer, ForeignKey('context.id'), primary_key=True),
                      Column('char_start', Integer, primary_key=True),
                      Column('char_end', Integer, primary_key=True),
                      Column('meta', PickleType),
                      ForeignKeyConstraint(['id', 'candidate_set_id'], ['candidate.id', 'candidate.candidate_set_id'])
                      )

    # Postgres requires an explicit unique index to use a tuple as a compound foreign key,
    # even if it is redundant as in this case
    if snorkel_postgres:
        __table_args__ = (
            Index('ngram_unique_id_candidate_set_id', __table__.c.id, __table__.c.candidate_set_id, unique=True),
        )

    context = relationship('Context', backref=backref('candidates', cascade_backrefs=False))

    __mapper_args__ = {
        'polymorphic_identity': 'ngram',
    }

    def __len__(self):
        return self.char_end - self.char_start + 1

    def __eq__(self, other):
        if isinstance(other, Ngram):
            return self.context == other.context and self.char_start == other.char_start and self.char_end == other.char_end
        else:
            return False

    def __hash__(self):
        return hash(self.context) + hash(self.char_start) + hash(self.char_end)

    # TODO: Below methods could be replaced with transient members, i.e., not persisted, using the @reconstructor decorator

    def get_word_start(self):
        return self.char_to_word_index(self.char_start)

    def get_word_end(self):
        return self.char_to_word_index(self.char_end)

    def get_n(self):
        return self.get_word_end() - self.get_word_start() + 1

    def get_sent_offset(self):
        return self.context.char_offsets[0]

    def get_sent_char_start(self):
        return self.char_start - self.get_sent_offset()

    def get_sent_char_end(self):
        return self.char_end - self.get_sent_offset()

    def char_to_word_index(self, ci):
        """Given a character-level index (offset), return the index of the **word this char is in**"""
        i = None
        for i, co in enumerate(self.context.char_offsets):
            if ci == co:
                return i
            elif ci < co:
                return i-1
        return i

    def word_to_char_index(self, wi):
        """Given a word-level index, return the character-level index (offset) of the word's start"""
        return self.context.char_offsets[wi]

    def get_attrib_tokens(self, a):
        """Get the tokens of sentence attribute _a_ over the range defined by word_offset, n"""
        return self.context.__getattribute__(a)[self.get_word_start():self.get_word_end() + 1]

    def get_attrib_span(self, a, sep=" "):
        """Get the span of sentence attribute _a_ over the range defined by word_offset, n"""
        # NOTE: Special behavior for words currently (due to correspondence with char_offsets)
        if a == 'words':
            return self.context.text[self.get_sent_char_start():self.get_sent_char_end() + 1]
        else:
            return sep.join(self.get_attrib_tokens(a))

    def get_span(self, sep=" "):
        return self.get_attrib_span('words', sep)

    def __getitem__(self, key):
        """
        Slice operation returns a new candidate sliced according to **char index**
        Note that the slicing is w.r.t. the candidate range (not the abs. sentence char indexing)
        """
        if isinstance(key, slice):
            char_start = self.char_start if key.start is None else self.char_start + key.start
            if key.stop is None:
                char_end = self.char_end
            elif key.stop >= 0:
                char_end = self.char_start + key.stop - 1
            else:
                char_end = self.char_end + key.stop
            return Ngram(char_start=char_start, char_end=char_end, context=self.context)
        else:
            raise NotImplementedError()

    def __repr__(self):
        return 'Ngram("%s", context=%s, chars=[%s,%s], words=[%s,%s])' \
            % (self.get_span(), self.context.id, self.char_start, self.char_end, self.get_word_start(),
               self.get_word_end())


class NgramPair(Candidate):
    """
    A pair of Ngram Candidates, representing a relation from Ngram 1 to Ngram 2.
    """
    __table__ = Table('ngram_pair', SnorkelBase.metadata,
                      Column('id', Integer, unique=True),
                      Column('candidate_set_id', Integer, primary_key=True),
                      Column('ngram0_id', Integer, primary_key=True),
                      Column('ngram1_id', Integer, primary_key=True),
                      ForeignKeyConstraint(['id', 'candidate_set_id'], ['candidate.id', 'candidate.candidate_set_id']),
                      ForeignKeyConstraint(['ngram0_id', 'candidate_set_id'], ['ngram.id', 'ngram.candidate_set_id']),
                      ForeignKeyConstraint(['ngram1_id', 'candidate_set_id'], ['ngram.id', 'ngram.candidate_set_id'])
                      )

    ngram0 = relationship('Ngram', backref=backref('ngram_source_pairs', cascade_backrefs=False),
                          cascade_backrefs=False, foreign_keys='NgramPair.ngram0_id')
    ngram1 = relationship('Ngram', backref=backref('ngram_dest_pairs', cascade_backrefs=False),
                          cascade_backrefs=False, foreign_keys='NgramPair.ngram1_id')

    __mapper_args__ = {
        'polymorphic_identity': 'ngram_pair',
    }

    def __getitem__(self, key):
        if key == 0:
            return self.ngram0
        elif key == 1:
            return self.ngram1
        else:
            raise KeyError('Valid keys are 0 and 1.')

    def __repr__(self):
        return "NgramPair(%s, %s)" % (self.ngram0, self.ngram1)
