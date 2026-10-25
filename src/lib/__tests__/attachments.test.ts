import {
  checkAttachment,
  formatFileSize,
  MAX_ATTACHMENT_BYTES,
  normalizeMediaType,
  selectAttachments,
} from '@/lib/attachments';

describe('normalizeMediaType', () => {
  it('normalizes image/jpg and letter case', () => {
    expect(normalizeMediaType('image/jpg', 'a.jpg')).toBe('image/jpeg');
    expect(normalizeMediaType('IMAGE/PNG', 'a.png')).toBe('image/png');
    expect(normalizeMediaType('application/pdf; charset=binary', 'a.pdf')).toBe('application/pdf');
  });

  it('uses the file extension when the type is missing or generic', () => {
    expect(normalizeMediaType(undefined, 'Report.PDF')).toBe('application/pdf');
    expect(normalizeMediaType('application/octet-stream', 'shot.webp')).toBe('image/webp');
    expect(normalizeMediaType(null, 'IMG_0001.HEIC')).toBe('image/heic');
    expect(normalizeMediaType('', 'notes')).toBe('');
  });
});

describe('checkAttachment', () => {
  it('accepts allowed images and PDFs up to 5 MB', () => {
    expect(checkAttachment({ name: 'a.png', mimeType: 'image/png', size: 10 })).toEqual({
      ok: true,
      mediaType: 'image/png',
    });
    expect(
      checkAttachment({ name: 'b.jpg', mimeType: 'image/jpg', size: MAX_ATTACHMENT_BYTES })
    ).toEqual({ ok: true, mediaType: 'image/jpeg' });
    // Size unknown until the file is read: checked again after reading.
    expect(checkAttachment({ name: 'c.pdf', mimeType: 'application/pdf' })).toEqual({
      ok: true,
      mediaType: 'application/pdf',
    });
  });

  it('rejects HEIC photos with a clear reason', () => {
    for (const file of [
      { name: 'IMG_1.HEIC', mimeType: 'image/heic', size: 100 },
      { name: 'IMG_2.heif', mimeType: null, size: 100 },
    ]) {
      const result = checkAttachment(file);
      expect(result.ok).toBe(false);
      expect(!result.ok && result.reason).toMatch(/HEIC/);
    }
  });

  it('rejects other types and files over 5 MB', () => {
    const textFile = checkAttachment({ name: 'notes.txt', mimeType: 'text/plain', size: 10 });
    expect(textFile.ok).toBe(false);
    expect(!textFile.ok && textFile.reason).toMatch(/can't be sent/);

    const big = checkAttachment({
      name: 'big.png',
      mimeType: 'image/png',
      size: MAX_ATTACHMENT_BYTES + 1,
    });
    expect(big).toEqual({ ok: false, reason: 'big.png is larger than 5 MB.' });
  });
});

describe('selectAttachments', () => {
  const png = (name: string) => ({ name, mimeType: 'image/png', size: 1000 });

  it('keeps at most 3 files, counting those already attached', () => {
    const result = selectAttachments([png('1.png'), png('2.png'), png('3.png')], 2);

    expect(result.accepted.map(({ file }) => file.name)).toEqual(['1.png']);
    expect(result.rejected).toEqual(['You can attach up to 3 files. 2 files were left out.']);
  });

  it('reports each rejected file and keeps the valid ones in order', () => {
    const result = selectAttachments(
      [png('a.png'), { name: 'b.heic', mimeType: 'image/heic', size: 1 }, png('c.png')],
      0
    );

    expect(result.accepted.map(({ file, mediaType }) => [file.name, mediaType])).toEqual([
      ['a.png', 'image/png'],
      ['c.png', 'image/png'],
    ]);
    expect(result.rejected).toHaveLength(1);
    expect(result.rejected[0]).toMatch(/b\.heic is a HEIC photo/);
  });

  it('uses the singular for one file left out', () => {
    expect(selectAttachments([png('x.png')], 3).rejected).toEqual([
      'You can attach up to 3 files. 1 file was left out.',
    ]);
  });
});

describe('formatFileSize', () => {
  it('shows KB below 1 MB and MB above', () => {
    expect(formatFileSize(200)).toBe('1 KB');
    expect(formatFileSize(640 * 1024)).toBe('640 KB');
    expect(formatFileSize(1.25 * 1024 * 1024)).toBe('1.3 MB');
  });
});
