/* Diorama's shelf and PC case, from the photo of the desk (firmware/tools/gen_desk.py -- don't edit) */
#ifndef CODA_DESK_ART_H
#define CODA_DESK_ART_H

#define DA_SHELF_X 20
#define DA_CLOCK_X 96.69f
#define DA_CLOCK_Y 14.91f
#define DA_CLOCK_R 7.33f

static const char DA_SHELF[24][128] = {
    ".....................940000279........iqrmjljiijiiiijjjggh9..............................9ggggghhhh99iiiikloppqqoifikolhlllprh.",
    ".....................222555324.......7dntnjmmjiiiiijmmjhjd9..............................dggjjjjjhddiikkikopqqqtriotofkolqqpptj",
    ".....................589787g858...dih97esqmmljjiiijmmmmjhgh..............................9dhhkfijh99elllkkoprvttvqttpiipqppqqth",
    ".....................52200299jhnnrmjrtd9jtnmmjiiillnmtnmjmmhjjh..........................9hjjfbihd99hlmqpkoptpprvtpooilppopqpqj",
    ".....................7442228dgjmjjnmnqtiirtnnljjjmmtmrnrrljmjhd....................ne...98dhhfffd799gjlrtpkookpqqliooipqppprpmn",
    ".....................ggg99hhd8jnhjmnnnqnnqtqnmljmptqrttqmqrmhd9...................tsd98bbaaaacffhd999gjtvvqokkqrokipqprtpqllpqr",
    "....................hggg758855555556itrnnrrtqnmmnqvntvrmnmhhhih..................jercaba536baaabokc999httqqokptppkkpqqqrtpkkpqn",
    "....................kggg725555555555emttrrrttnrqmuvvvttthdd99dhhhhhd...h.......htvrfabb3532abaaapqod7dmqrllqppsppokkopqqtolkpqj",
    "....................kpjg923238888885emntvssssssussuvsurjhhjehijijjiljdmv.........vpbbbb33626bbbafkkf9jrrupotupspspoooorttrplksj",
    "....................fpuha22355555585ermqtvusussuusuussmjjrtrnnnmjddjmnr...........kbbbb6666abbbbfbbbfqqpprrtssplsrppootvqqpkfnj",
    ".....................opte222555535a5cjlmruvsuuuuuuuuusnuurjhjjhhed9dln.............bbbabbbbbbbbfofbbkinsssvsssopsvpqoktlkpokfmh",
    ".....................ooqe22025533585enlmnnuuuuuuuvuuuvvunljmhe99dddeem..............fbbbbbbfbackkbbfoluvussussppsrtqiooootpkkmj",
    ".......e.......7ekokfooqe00022233285evurrnuuuussvuuuuuusnrnjhhh79hdjr...............99997799d74loffkqvvvvssusuuuuuvplokpotrpojj",
    ".......rhhhdhd.dghkkfkpqc00000055285cusvvrnmsuuuuvusuvvtujd99jm9dmdrn...............47447174494mooqssqvussutmgd97dmvtoooorppool",
    ".....h9lmihjiijjdhkkilppe000235688a5ctijvsnnnussuususstnjd777nh7enelm................9444444479qkfoppkspksn41111117lqoookrppoop",
    ".....himmjhihhje9ellkpkoi00255566652cj77jvutuussnnvvuqhh99799j97jqmmj...............994444474drpfkosokpopum111111714toookroppqp",
    "......hllnjmttnhedhmnllsf02355553332ef8afddnunlmsvvvund777dshdd9hsnnl...............hj7477979vvkkosvopppvvn11111111dtoooptptttq",
    "......9sne8888adcosuvsurk0222223335ckkabchhnssmnsvvvsm97779h99unnsssm...............jvj79hhdlqkfkoa6666666e11111149vtpppttpqttt",
    "....9ie8a2000002cc85558fo2068533338caf744dfnussnuvvvmd97777779nnmsssta..............skc9dfcdfaakkl33333333411111179ttttttropttt",
    "...9fia002000025c5000028r25eeek8788777777779mmlsvulsj977777h9dnljnnsvm.............eh9bddkfechfkol33333335941111479pltvvtqqqqqq",
    "...8bbb222000025d820022as3ae8aabaaa86666635aaa63huluj97779jvuuuslmnmsmm...........hme2ad8jfllmqkfe33333336.....g17jniirrqtpoppp",
    "...bbbb502000025d820022at666826ffaaaa666666bkib3cnjuh79ddhlmssvusssnusnm.........jsuiaadgjnnjdccc8655666................jkffcio",
    "...cbbf822200025j920022cv66666affbaa6666666folktvjlvjhjvdhjmlmmmjnmlqnlld52.............................................jqkfcko",
    "...cbfe822200027jd20002ev66a66kklkbbbbccccchhheed8......748jlldd89lnh...................................................jrtpqpq",
};
static const px16 DA_SHELF_PAL[32] = { 0xffdb, 0xf6ed, 0xd6b9, 0xa657, 0xd52e, 0xa534, 0x6d11, 0xa3ea, 0x83ee, 0x8308, 0x53ac, 0x2ba9, 0x4aa7, 0x5a47, 0x4247, 0x2a45, 0x59a5, 0x3984, 0x29a4, 0x2903, 0x1184, 0x1103, 0x10a3, 0x1062, 0x0903, 0x00a2, 0x0082, 0x0061, 0x0042, 0x0021, 0x0001, 0x0001 };

static const char DA_CASE[34][26] = {
    ".........................",
    ".....9.9b9999c...........",
    "....99899b9999c..........",
    "....c9999999999c.........",
    ".....c9999bb99bbb........",
    ".....cb999bbbabbbb.......",
    "...ffcccb9bbbbabbabc.....",
    "..efeeccbb9abbbbbbbcc....",
    ".edeedeccb999abbbbbbc....",
    ".edddddccbbbbbbccccccc...",
    ".dddddda2224444444666677.",
    ".eadddea0000000000000000.",
    ".ed8ddda0000111111111111.",
    ".ed3adda0000121111221211.",
    ".ed3ddda0010111131422221.",
    ".ee8ddda0111134332444221.",
    ".efdddda0021134334224322.",
    "..eeedda0112444334444442.",
    "..fffedd1124455556654542.",
    "...ffefd1344555765456664.",
    "...ffffd1445557766566662.",
    "....fffe1345556676666652.",
    ".....ffd1335566677767764.",
    ".....ffe1345556777777774.",
    "......ff1344435765787653.",
    "......ff3333345456777753a",
    ".......f1111124455676664.",
    "........4311111355465663.",
    ".........................",
    ".........................",
    ".........70..............",
    "..........a..............",
    ".........................",
    ".........................",
};
static const px16 DA_CASE_PAL[16] = { 0xef7c, 0xdf1b, 0xdeda, 0xceb9, 0xce98, 0xc678, 0xc637, 0xc617, 0xad75, 0x9cb0, 0x8c72, 0x8c2f, 0x7bce, 0x63b2, 0x5b4f, 0x4acf };

#endif
