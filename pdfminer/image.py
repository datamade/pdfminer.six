import os
import os.path
import struct
from io import BytesIO

from .jbig2 import JBIG2StreamReader, JBIG2StreamWriter
from .pdfcolor import LITERAL_DEVICE_CMYK
from .pdfcolor import LITERAL_DEVICE_GRAY
from .pdfcolor import LITERAL_DEVICE_RGB
from .pdftypes import (LITERALS_DCT_DECODE,
                       LITERALS_JBIG2_DECODE,
                       LITERALS_JPX_DECODE)


def align32(x):
    return ((x+3)//4)*4


class BMPWriter:
    def __init__(self, fp, bits, width, height):
        self.fp = fp
        self.bits = bits
        self.width = width
        self.height = height
        if bits == 1:
            ncols = 2
        elif bits == 8:
            ncols = 256
        elif bits == 24:
            ncols = 0
        else:
            raise ValueError(bits)
        self.linesize = align32((self.width*self.bits+7)//8)
        self.datasize = self.linesize * self.height
        headersize = 14+40+ncols*4
        info = struct.pack('<IiiHHIIIIII', 40, self.width, self.height,
                           1, self.bits, 0, self.datasize, 0, 0, ncols, 0)
        assert len(info) == 40, str(len(info))
        header = struct.pack('<ccIHHI', b'B', b'M',
                             headersize+self.datasize, 0, 0, headersize)
        assert len(header) == 14, str(len(header))
        self.fp.write(header)
        self.fp.write(info)
        if ncols == 2:
            # B&W color table
            for i in (0, 255):
                self.fp.write(struct.pack('BBBx', i, i, i))
        elif ncols == 256:
            # grayscale color table
            for i in range(256):
                self.fp.write(struct.pack('BBBx', i, i, i))
        self.pos0 = self.fp.tell()
        self.pos1 = self.pos0 + self.datasize
        return

    def write_line(self, y, data):
        self.fp.seek(self.pos1 - (y+1)*self.linesize)
        self.fp.write(data)
        return


class ImageWriter:
    """Write image to a file

    Supports various image types: JPEG, JBIG2 and bitmaps
    """

    def __init__(self, outdir):
        self.outdir = outdir
        if not os.path.exists(self.outdir):
            os.makedirs(self.outdir)
        self.seen_files = set()
        return

    def export_image(self, image):
        (width, height) = image.srcsize

        is_jbig2 = self.is_jbig2_image(image)
        ext = self._get_image_extension(image, width, height, is_jbig2)
        name, path = self._create_unique_image_name(self.outdir,
                                                    image.name, ext)

        if not os.path.exists(path):        
            fp = open(path, 'wb')
            if ext == '.jpg':
                raw_data = image.stream.get_rawdata()
                if LITERAL_DEVICE_CMYK in image.colorspace:
                    from PIL import Image
                    from PIL import ImageChops
                    ifp = BytesIO(raw_data)
                    i = Image.open(ifp)
                    i = ImageChops.invert(i)
                    i = i.convert('RGB')
                    i.save(fp, 'JPEG')
                else:
                    fp.write(raw_data)
            elif ext == '.jp2':
                # if we just write the raw data, most image programs
                # that I have tried cannot open the file. However,
                # if open and saving with PIL produces a file that
                # seems to be easily opened by other programs
                from PIL import Image
                raw_data = image.stream.get_rawdata()
                ifp = BytesIO(raw_data)
                i = Image.open(ifp)
                i.save(fp, 'JPEG2000')
            elif is_jbig2:
                input_stream = BytesIO()
                input_stream.write(image.stream.get_data())
                input_stream.seek(0)
                reader = JBIG2StreamReader(input_stream)
                segments = reader.get_segments()

                writer = JBIG2StreamWriter(fp)
                writer.write_file(segments)
            elif image.bits == 1:
                bmp = BMPWriter(fp, 1, width, height)
                data = image.stream.get_data()
                i = 0
                width = (width+7)//8
                for y in range(height):
                    bmp.write_line(y, data[i:i+width])
                    i += width
            elif image.bits == 8 and LITERAL_DEVICE_RGB in image.colorspace:
                bmp = BMPWriter(fp, 24, width, height)
                data = image.stream.get_data()
                i = 0
                width = width*3
                for y in range(height):
                    bmp.write_line(y, data[i:i+width])
                    i += width
            elif image.bits == 8 and LITERAL_DEVICE_GRAY in image.colorspace:
                bmp = BMPWriter(fp, 8, width, height)
                data = image.stream.get_data()
                i = 0
                for y in range(height):
                    bmp.write_line(y, data[i:i+width])
                    i += width
            else:
                fp.write(image.stream.get_data())
            fp.close()
        return name

    @staticmethod
    def is_jbig2_image(image):
        filters = image.stream.get_filters()
        is_jbig2 = False
        for filter_name, params in filters:
            if filter_name in LITERALS_JBIG2_DECODE:
                is_jbig2 = True
                break
        return is_jbig2

    @staticmethod
    def _get_image_extension(image, width, height, is_jbig2):
        filters = image.stream.get_filters()
        if len(filters) == 1 and filters[0][0] in LITERALS_DCT_DECODE:
            ext = '.jpg'
        elif len(filters) == 1 and filters[0][0] in LITERALS_JPX_DECODE:
            ext = '.jp2'
        elif is_jbig2:
            ext = '.jb2'
        elif (image.bits == 1 or
              image.bits == 8 and
              (LITERAL_DEVICE_RGB in image.colorspace or
               LITERAL_DEVICE_GRAY in image.colorspace)):
            ext = '.%dx%d.bmp' % (width, height)
        else:
            ext = '.%d.%dx%d.img' % (image.bits, width, height)
        return ext

    def _create_unique_image_name(self, dirname, image_name, ext):
        name = image_name + ext
        path = os.path.join(dirname, name)
        img_index = 0
        while path in self.seen_files:
            name = '%s.%d%s' % (image_name, img_index, ext)
            path = os.path.join(dirname, name)
            img_index += 1
        self.seen_files.add(path)
        return name, path
