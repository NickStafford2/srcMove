// Extracted from OpenCV; see the case provenance and README.
namespace cv {
struct IPPReorderGeneralFunctor
{
    IPPReorderGeneralFunctor(ippiReorderFunc _func1, ippiGeneralFunc _func2, int _order0, int _order1, int _order2, int _depth) :
        ippiColorConvertReorder(_func1), ippiColorConvertGeneral(_func2), depth(_depth)
    {
        order[0] = _order0;
        order[1] = _order1;
        order[2] = _order2;
        order[3] = 3;
    }
    bool operator()(const void *src, int srcStep, void *dst, int dstStep, int cols, int rows) const
    {
        if (ippiColorConvertReorder == 0 || ippiColorConvertGeneral == 0)
            return false;

        Mat temp;
        temp.create(rows, cols, CV_MAKETYPE(depth, 3));
        if(CV_INSTRUMENT_FUN_IPP(ippiColorConvertReorder, src, srcStep, temp.ptr(), (int)temp.step[0], ippiSize(cols, rows), order) < 0)
            return false;
        return CV_INSTRUMENT_FUN_IPP(ippiColorConvertGeneral, temp.ptr(), (int)temp.step[0], dst, dstStep, ippiSize(cols, rows)) >= 0;
    }
private:
    ippiReorderFunc ippiColorConvertReorder;
    ippiGeneralFunc ippiColorConvertGeneral;
    int order[4];
    int depth;
};

struct IPPGeneralReorderFunctor
{
    IPPGeneralReorderFunctor(ippiGeneralFunc _func1, ippiReorderFunc _func2, int _order0, int _order1, int _order2, int _depth) :
        ippiColorConvertGeneral(_func1), ippiColorConvertReorder(_func2), depth(_depth)
    {
        order[0] = _order0;
        order[1] = _order1;
        order[2] = _order2;
        order[3] = 3;
    }
    bool operator()(const void *src, int srcStep, void *dst, int dstStep, int cols, int rows) const
    {
        if (ippiColorConvertGeneral == 0 || ippiColorConvertReorder == 0)
            return false;

        Mat temp;
        temp.create(rows, cols, CV_MAKETYPE(depth, 3));
        if(CV_INSTRUMENT_FUN_IPP(ippiColorConvertGeneral, src, srcStep, temp.ptr(), (int)temp.step[0], ippiSize(cols, rows)) < 0)
            return false;
        return CV_INSTRUMENT_FUN_IPP(ippiColorConvertReorder, temp.ptr(), (int)temp.step[0], dst, dstStep, ippiSize(cols, rows), order) >= 0;
    }
private:
    ippiGeneralFunc ippiColorConvertGeneral;
    ippiReorderFunc ippiColorConvertReorder;
    int order[4];
    int depth;
};
}
